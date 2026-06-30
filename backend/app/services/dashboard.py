"""Dashboard aggregation service (backend_design_prd 절차 11, §11.1/§13.1)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import L2Flag
from app.domain.schemas import DashboardMetrics
from app.models.orm import LabelL2Consensus
from app.repositories.datasets import GoldVersionRepository
from app.repositories.drift import DriftRepository
from app.repositories.labels import LabelRepository
from app.repositories.reviews import ReviewRepository


class DashboardService:
    def __init__(self, session: Session):
        self.session = session
        self.labels = LabelRepository(session)
        self.reviews = ReviewRepository(session)
        self.drift = DriftRepository(session)
        self.gold = GoldVersionRepository(session)

    def metrics(self) -> DashboardMetrics:
        # Single GROUP BY for total+failed per method, total derived from it
        # (OPTIMIZATION_PLAN C2 — was 3 separate count queries).
        counts = self.labels.l1_total_and_failed_by_method()
        by_method = {m: total for m, (total, _f) in counts.items()}
        failure_rate = {
            m: (f / total) if total else 0.0 for m, (total, f) in counts.items()
        }
        total_l1 = sum(by_method.values())

        total_l2 = self.session.scalar(select(func.count()).select_from(LabelL2Consensus)) or 0
        agreed_l2 = (
            self.session.scalar(
                select(func.count()).select_from(LabelL2Consensus).where(LabelL2Consensus.flag == L2Flag.AGREED.value)
            )
            or 0
        )
        agreement_rate = (agreed_l2 / total_l2) if total_l2 else 0.0

        active_gold = self.gold.active()
        return DashboardMetrics(
            total_l1=total_l1,
            l1_by_method=by_method,
            failure_rate_by_method=failure_rate,
            avg_confidence_by_method=self.labels.avg_confidence_by_method(),
            l2_agreement_rate=agreement_rate,
            human_review_queue_size=self.reviews.count_pending(),
            l3_count=self.labels.count_l3(),
            drift_status_by_method=self.drift.latest_status_by_method(),
            gold_label_version=active_gold.label_version if active_gold else None,
        )
