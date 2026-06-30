"""Label repository: L1/L2/L3 data access (backend_design_prd 절차 1).

Enforces the append-only invariant (README §4, NFR-4) at the application layer:
L1 rows are never updated in place; corrections create a new row and flip the old
one to SUPERSEDED. Production additionally guards this with a Postgres trigger
(db_design_prd 절차 2).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.domain.enums import L1Status, L3Status
from app.domain.schemas import LabelObjectIn
from app.errors import SchemaValidationError
from app.models.orm import LabelL1Candidate, LabelL2Consensus, LabelL3Gold
from app.util import IN_CHUNK, chunked, new_id, now_utc


class LabelRepository:
    def __init__(self, session: Session):
        self.session = session

    # ----------------------------------------------------------------- L1
    def create_l1(self, payload: LabelObjectIn, *, status: L1Status = L1Status.CREATED) -> LabelL1Candidate:
        """Persist an L1 candidate. Raises SchemaValidationError (→422) when the
        required ``inputs_hash`` or ``method_ver`` is missing (FR-1 수용 기준)."""
        if not payload.inputs_hash:
            raise SchemaValidationError("inputs_hash is required", details={"field": "inputs_hash"})
        if not payload.method_ver:
            raise SchemaValidationError("method_ver is required", details={"field": "method_ver"})

        row = LabelL1Candidate(
            label_id=new_id("l1"),
            sample_id=payload.sample_id,
            feature_id=payload.feature_id,
            feature_version=payload.feature_version,
            value=payload.value,
            task_type=payload.task_type,
            method=payload.method.value,
            method_ver=payload.method_ver,
            confidence=payload.confidence,
            rationale=payload.rationale,
            inputs_hash=payload.inputs_hash,
            labeled_at=payload.labeled_at or now_utc(),
            run_id=payload.run_id,
            agreement_group_id=payload.agreement_group_id,
            status=status.value,
            extra_metadata=payload.metadata,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_l1_by_sample(self, sample_id: str, *, active_only: bool = True) -> list[LabelL1Candidate]:
        stmt = select(LabelL1Candidate).where(LabelL1Candidate.sample_id == sample_id)
        if active_only:
            stmt = stmt.where(LabelL1Candidate.status == L1Status.CREATED.value)
        return list(self.session.scalars(stmt.order_by(LabelL1Candidate.labeled_at)))

    def get_l1_by_ids(self, label_ids: list[str]) -> list[LabelL1Candidate]:
        if not label_ids:
            return []
        rows: list[LabelL1Candidate] = []
        for chunk in chunked(label_ids, IN_CHUNK):
            stmt = select(LabelL1Candidate).where(LabelL1Candidate.label_id.in_(chunk))
            rows.extend(self.session.scalars(stmt))
        return rows

    def get_l1_by_samples(
        self, sample_ids: list[str], *, active_only: bool = False
    ) -> dict[str, list[LabelL1Candidate]]:
        """Batch-load L1 candidates for many samples in a single IN query per chunk,
        grouped by ``sample_id`` (avoids the per-sample N+1 in fusion)."""
        out: dict[str, list[LabelL1Candidate]] = defaultdict(list)
        if not sample_ids:
            return out
        for chunk in chunked(list(sample_ids), IN_CHUNK):
            stmt = select(LabelL1Candidate).where(LabelL1Candidate.sample_id.in_(chunk))
            if active_only:
                stmt = stmt.where(LabelL1Candidate.status == L1Status.CREATED.value)
            for row in self.session.scalars(stmt.order_by(LabelL1Candidate.labeled_at)):
                out[row.sample_id].append(row)
        return out

    def get_l1_by_run(
        self, run_id: str, *, limit: Optional[int] = None, offset: int = 0
    ) -> list[LabelL1Candidate]:
        stmt = (
            select(LabelL1Candidate)
            .where(LabelL1Candidate.run_id == run_id)
            .order_by(LabelL1Candidate.labeled_at)
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    def get_l1_by_method_ver(
        self, method_ver: str, *, limit: Optional[int] = None, offset: int = 0
    ) -> list[LabelL1Candidate]:
        """Lineage query: labels produced by a given labeler version / prompt hash (FR-10)."""
        stmt = select(LabelL1Candidate).where(LabelL1Candidate.method_ver == method_ver).order_by(
            LabelL1Candidate.labeled_at
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    def all_sample_ids(self) -> list[str]:
        """Distinct sample ids across all L1 candidates (gold republish full scope)."""
        return list(self.session.scalars(select(func.distinct(LabelL1Candidate.sample_id))))

    def supersede_l1(self, label_id: str) -> None:
        row = self.session.get(LabelL1Candidate, label_id)
        if row is not None:
            row.status = L1Status.SUPERSEDED.value
            self.session.flush()

    # ----------------------------------------------------------------- L2
    def create_l2(
        self,
        *,
        sample_id,
        value,
        confidence,
        fusion_policy,
        fusion_version,
        source_l1_ids,
        agreement_score,
        flag,
        fusion_reason,
        label_version,
        run_id=None,
        agreement=None,
    ) -> LabelL2Consensus:
        row = LabelL2Consensus(
            consensus_label_id=new_id("l2"),
            sample_id=sample_id,
            value=value,
            confidence=confidence,
            fusion_policy=fusion_policy,
            fusion_version=fusion_version,
            source_l1_ids=list(source_l1_ids),
            agreement_score=agreement_score,
            agreement=agreement,
            flag=flag,
            fusion_reason=fusion_reason,
            created_at=now_utc(),
            label_version=label_version,
            run_id=run_id,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_l2_by_sample(self, sample_id: str) -> Optional[LabelL2Consensus]:
        stmt = (
            select(LabelL2Consensus)
            .where(LabelL2Consensus.sample_id == sample_id)
            .order_by(LabelL2Consensus.created_at.desc())
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def list_l2_by_version(self, label_version: str) -> list[LabelL2Consensus]:
        stmt = select(LabelL2Consensus).where(LabelL2Consensus.label_version == label_version)
        return list(self.session.scalars(stmt))

    # ----------------------------------------------------------------- L3
    def create_l3(
        self,
        *,
        sample_id,
        value,
        reviewer_id,
        review_reason,
        source_review_id,
        source_l1_ids,
        label_version,
    ) -> LabelL3Gold:
        """Create a new active L3, superseding any prior active L3 for the sample
        to preserve version history (FR-6, db_design_prd 절차 4)."""
        prior = self.get_l3_by_sample(sample_id)
        row = LabelL3Gold(
            gold_label_id=new_id("l3"),
            sample_id=sample_id,
            value=value,
            reviewer_id=reviewer_id,
            review_reason=review_reason,
            source_review_id=source_review_id,
            source_l1_ids=list(source_l1_ids) if source_l1_ids else None,
            created_at=now_utc(),
            label_version=label_version,
            status=L3Status.ACTIVE.value,
        )
        self.session.add(row)
        self.session.flush()
        if prior is not None:
            prior.status = L3Status.SUPERSEDED.value
            prior.superseded_by = row.gold_label_id
            self.session.flush()
        return row

    def get_l3_by_sample(self, sample_id: str) -> Optional[LabelL3Gold]:
        stmt = (
            select(LabelL3Gold)
            .where(LabelL3Gold.sample_id == sample_id, LabelL3Gold.status == L3Status.ACTIVE.value)
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def get_active_l3_by_samples(self, sample_ids: list[str]) -> dict[str, LabelL3Gold]:
        """Batch-load the active L3 gold label for many samples (avoids per-sample
        N+1 in the dataset builder). Returns ``{sample_id: LabelL3Gold}``."""
        out: dict[str, LabelL3Gold] = {}
        if not sample_ids:
            return out
        for chunk in chunked(list(sample_ids), IN_CHUNK):
            stmt = select(LabelL3Gold).where(
                LabelL3Gold.sample_id.in_(chunk),
                LabelL3Gold.status == L3Status.ACTIVE.value,
            )
            for row in self.session.scalars(stmt):
                out[row.sample_id] = row
        return out

    # ----------------------------------------------------------------- counts
    def l1_total_and_failed_by_method(self) -> dict[str, tuple[int, int]]:
        """Total and FAILED L1 counts per method in a single GROUP BY query
        (OPTIMIZATION_PLAN C2 — replaces 3 separate dashboard count queries)."""
        stmt = select(
            LabelL1Candidate.method,
            func.count(),
            func.sum(case((LabelL1Candidate.status == L1Status.FAILED.value, 1), else_=0)),
        ).group_by(LabelL1Candidate.method)
        return {
            m: (int(total), int(failed or 0))
            for m, total, failed in self.session.execute(stmt)
        }

    def avg_confidence_by_method(self) -> dict[str, float]:
        stmt = (
            select(LabelL1Candidate.method, func.avg(LabelL1Candidate.confidence))
            .where(LabelL1Candidate.confidence.is_not(None))
            .group_by(LabelL1Candidate.method)
        )
        return {m: float(a) for m, a in self.session.execute(stmt) if a is not None}

    def count_l3(self) -> int:
        stmt = select(func.count()).select_from(LabelL3Gold).where(LabelL3Gold.status == L3Status.ACTIVE.value)
        return self.session.scalar(stmt) or 0
