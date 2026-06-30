"""Human Review service (backend_design_prd 절차 5/6, FR-5/FR-6, §10.3)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.domain.enums import L2Flag, ReviewStatus
from app.domain.schemas import (
    ReviewCompleteRequest,
    ReviewCompleteResponse,
    ReviewCreateRequest,
    ReviewCreateResponse,
    ReviewListResponse,
    ReviewView,
)
from app.errors import ConflictError, NotFoundError
from app.repositories.audit import AuditRepository
from app.repositories.datasets import GoldVersionRepository
from app.repositories.labels import LabelRepository
from app.repositories.reviews import ReviewRepository
from app.repositories.runs import RunRepository
from app.services.fusion import build_agreement_record


class ReviewService:
    def __init__(self, session: Session):
        self.session = session
        self.reviews = ReviewRepository(session)
        self.labels = LabelRepository(session)
        self.audit = AuditRepository(session)
        self.gold = GoldVersionRepository(session)
        self.runs = RunRepository(session)

    def register(self, req: ReviewCreateRequest, *, actor: Optional[str] = None) -> ReviewCreateResponse:
        review = self.reviews.create(
            sample_id=req.sample_id,
            reason=req.reason,
            priority=req.priority,
            l1_label_ids=req.l1_label_ids,
        )
        self.audit.record(
            entity_type="review",
            entity_id=review.review_id,
            action="register",
            actor=actor,
            details={"reason": req.reason},
        )
        return ReviewCreateResponse(review_id=review.review_id, status=ReviewStatus(review.status))

    def list(self, *, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> ReviewListResponse:
        rows = self.reviews.list(status=status, limit=limit, offset=offset)
        return ReviewListResponse(reviews=[ReviewView.model_validate(r) for r in rows])

    def get_one(self, review_id: str) -> ReviewView:
        row = self.reviews.get(review_id)
        if row is None:
            raise NotFoundError(f"review {review_id} not found")
        return ReviewView.model_validate(row)

    def complete(
        self, review_id: str, req: ReviewCompleteRequest, *, actor: Optional[str] = None
    ) -> ReviewCompleteResponse:
        review = self.reviews.get(review_id)
        if review is None:
            raise NotFoundError(f"review {review_id} not found")
        if review.status == ReviewStatus.COMPLETED.value:
            raise ConflictError(f"review {review_id} already completed")

        active_gold = self.gold.active()
        label_version = active_gold.label_version if active_gold else "lv-l3"

        # 1. Create L3 gold-standard label (supersedes any prior active L3).
        l3 = self.labels.create_l3(
            sample_id=review.sample_id,
            value=req.value,
            reviewer_id=req.reviewer_id,
            review_reason=req.review_reason,
            source_review_id=review.review_id,
            source_l1_ids=review.l1_label_ids,
            label_version=label_version,
        )
        # 2. Close the review.
        self.reviews.set_status(review_id, ReviewStatus.COMPLETED, assigned_to=req.reviewer_id, completed=True)
        self.audit.record(
            entity_type="l3",
            entity_id=l3.gold_label_id,
            action="create",
            actor=req.reviewer_id,
            details={"review_id": review.review_id, "review_reason": req.review_reason},
        )

        # 2b. Closed loop (논문 §3.3): L3 검수 결과를 라벨러별 회귀 검증 신호로 재투입한다.
        #     각 L1 라벨러(method_ver)가 사람 정답과 일치했는지를 audit에 기록하여,
        #     규칙 추가·LLM 프롬프트 회귀 검증의 입력으로 사용할 수 있게 한다.
        source_l1s = self.labels.get_l1_by_ids(list(review.l1_label_ids or []))
        if source_l1s:
            feedback = [
                {
                    "label_id": l.label_id,
                    "method": l.method,
                    "method_ver": l.method_ver,
                    "predicted": l.value,
                    "gold": req.value,
                    "agreed": l.value == req.value,
                }
                for l in source_l1s
            ]
            self.audit.record(
                entity_type="l3",
                entity_id=l3.gold_label_id,
                action="closed_loop_feedback",
                actor=req.reviewer_id,
                details={"sample_id": review.sample_id, "feedback": feedback},
            )

        # 3. Optionally regenerate L2 from the human decision (FR-5 수용 기준: L3 후 L2 재생성).
        if req.regenerate_l2:
            l2 = self.labels.create_l2(
                sample_id=review.sample_id,
                value=req.value,
                confidence=1.0,
                fusion_policy="human_priority",
                fusion_version="fusion-v1",
                source_l1_ids=review.l1_label_ids,
                agreement_score=1.0,
                agreement=build_agreement_record(source_l1s),
                flag=L2Flag.AGREED.value,
                fusion_reason="l3_regeneration",
                label_version=label_version,
            )
            self.audit.record(
                entity_type="l2",
                entity_id=l2.consensus_label_id,
                action="regenerate",
                actor=req.reviewer_id,
                details={"source_l3": l3.gold_label_id},
            )

        return ReviewCompleteResponse(gold_label_id=l3.gold_label_id, status=ReviewStatus.COMPLETED)
