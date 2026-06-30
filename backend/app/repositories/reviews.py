"""Human review queue repository (backend_design_prd 절차 5, FR-5)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import ReviewStatus
from app.models.orm import HumanReviewQueue
from app.util import IN_CHUNK, chunked, new_id, now_utc


class ReviewRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, sample_id, reason, priority=0, l1_label_ids=None) -> HumanReviewQueue:
        row = HumanReviewQueue(
            review_id=new_id("review"),
            sample_id=sample_id,
            reason=reason,
            priority=priority,
            l1_label_ids=list(l1_label_ids or []),
            status=ReviewStatus.PENDING.value,
            created_at=now_utc(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get(self, review_id: str) -> Optional[HumanReviewQueue]:
        return self.session.get(HumanReviewQueue, review_id)

    def list(
        self, *, status: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> list[HumanReviewQueue]:
        stmt = select(HumanReviewQueue)
        if status:
            stmt = stmt.where(HumanReviewQueue.status == status)
        stmt = (
            stmt.order_by(HumanReviewQueue.priority.desc(), HumanReviewQueue.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt))

    def pending_for_sample(self, sample_id: str) -> Optional[HumanReviewQueue]:
        stmt = select(HumanReviewQueue).where(
            HumanReviewQueue.sample_id == sample_id,
            HumanReviewQueue.status.in_([ReviewStatus.PENDING.value, ReviewStatus.IN_PROGRESS.value]),
        )
        return self.session.scalars(stmt).first()

    def pending_sample_ids(self, sample_ids: list[str]) -> set[str]:
        """Sample ids (among the given) that already have an open review — one query
        instead of a per-sample check (OPTIMIZATION_PLAN A4)."""
        if not sample_ids:
            return set()
        out: set[str] = set()
        for chunk in chunked(list(sample_ids), IN_CHUNK):
            stmt = select(HumanReviewQueue.sample_id).where(
                HumanReviewQueue.sample_id.in_(chunk),
                HumanReviewQueue.status.in_([ReviewStatus.PENDING.value, ReviewStatus.IN_PROGRESS.value]),
            )
            out.update(self.session.scalars(stmt))
        return out

    def set_status(self, review_id: str, status: ReviewStatus, *, assigned_to=None, completed=False):
        row = self.get(review_id)
        if row is None:
            return None
        row.status = status.value
        if assigned_to is not None:
            row.assigned_to = assigned_to
        if completed:
            row.completed_at = now_utc()
        self.session.flush()
        return row

    def count_pending(self) -> int:
        stmt = (
            select(func.count())
            .select_from(HumanReviewQueue)
            .where(HumanReviewQueue.status.in_([ReviewStatus.PENDING.value, ReviewStatus.IN_PROGRESS.value]))
        )
        return self.session.scalar(stmt) or 0
