"""Drift metric repository (backend_design_prd 절차 8, FR-7)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import L3Status
from app.models.orm import LabelDriftMetric, LabelL1Candidate, LabelL3Gold
from app.util import IN_CHUNK, chunked, new_id, now_utc


class DriftRepository:
    def __init__(self, session: Session):
        self.session = session

    # --------------------------------------------------- L1/L3 reads for drift
    def l1_value_meta_in_window(
        self, method: str, method_ver: str, start: datetime, end: datetime
    ) -> list[tuple]:
        """(value, metadata) pairs of a labeler's L1 in a time window (distribution drift)."""
        stmt = select(LabelL1Candidate.value, LabelL1Candidate.extra_metadata).where(
            LabelL1Candidate.method == method,
            LabelL1Candidate.method_ver == method_ver,
            LabelL1Candidate.labeled_at >= start,
            LabelL1Candidate.labeled_at < end,
        )
        return list(self.session.execute(stmt).all())

    def active_anchor_values(self) -> dict[str, object]:
        """{sample_id: value} for active L3 gold anchors."""
        return dict(
            self.session.execute(
                select(LabelL3Gold.sample_id, LabelL3Gold.value).where(
                    LabelL3Gold.status == L3Status.ACTIVE.value
                )
            ).all()
        )

    def active_anchor_sample_ids(self) -> list[str]:
        return list(
            self.session.scalars(
                select(LabelL3Gold.sample_id).where(LabelL3Gold.status == L3Status.ACTIVE.value)
            )
        )

    def l1_values_for_samples_in_window(
        self, sample_ids: list[str], method: str, start: datetime, end: datetime
    ) -> list[tuple]:
        """(sample_id, value) of a labeler's L1 for the given samples in a window,
        ordered by labeled_at (chunked IN). Used for anchor accuracy."""
        rows: list[tuple] = []
        for chunk in chunked(list(sample_ids), IN_CHUNK):
            stmt = (
                select(LabelL1Candidate.sample_id, LabelL1Candidate.value)
                .where(
                    LabelL1Candidate.sample_id.in_(chunk),
                    LabelL1Candidate.method == method,
                    LabelL1Candidate.labeled_at >= start,
                    LabelL1Candidate.labeled_at < end,
                )
                .order_by(LabelL1Candidate.labeled_at)
            )
            rows.extend(self.session.execute(stmt).all())
        return rows

    def create(
        self,
        *,
        method,
        method_ver,
        baseline_window,
        current_window,
        psi,
        kl_divergence,
        anchor_accuracy,
        status,
    ) -> LabelDriftMetric:
        row = LabelDriftMetric(
            metric_id=new_id("drift"),
            method=method,
            method_ver=method_ver,
            baseline_window=baseline_window,
            current_window=current_window,
            psi=psi,
            kl_divergence=kl_divergence,
            anchor_accuracy=anchor_accuracy,
            status=status,
            measured_at=now_utc(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list(self, *, method=None, limit=100, offset=0) -> list[LabelDriftMetric]:
        stmt = select(LabelDriftMetric)
        if method:
            stmt = stmt.where(LabelDriftMetric.method == method)
        stmt = stmt.order_by(LabelDriftMetric.measured_at.desc()).limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    def latest_status_by_method(self) -> dict[str, str]:
        """Latest drift status per method without loading the whole metrics table:
        join each method's MAX(measured_at) back to its row (OPTIMIZATION_PLAN A6)."""
        latest = (
            select(
                LabelDriftMetric.method.label("method"),
                func.max(LabelDriftMetric.measured_at).label("mt"),
            )
            .group_by(LabelDriftMetric.method)
            .subquery()
        )
        stmt = (
            select(LabelDriftMetric.method, LabelDriftMetric.status)
            .join(
                latest,
                (LabelDriftMetric.method == latest.c.method)
                & (LabelDriftMetric.measured_at == latest.c.mt),
            )
            # Deterministic tie-break when two rows share MAX(measured_at) (engine-agnostic).
            .order_by(LabelDriftMetric.method, LabelDriftMetric.metric_id)
        )
        out: dict[str, str] = {}
        for method, status in self.session.execute(stmt):
            out.setdefault(method, status)  # tie → keep lowest metric_id deterministically
        return out
