"""L1 generation pipeline (backend_design_prd 절차 2/3, §10.1).

Runs a set of labeler adapters over a sample and persists each result as an L1 row.
Failed/skipped adapter outputs are recorded as FAILED/SKIPPED rows (with a synthetic
value) so the run is auditable without crashing the pipeline (NFR-2).
"""
from __future__ import annotations

from typing import Sequence

from sqlalchemy.orm import Session

from app.domain.enums import L1Status
from app.domain.schemas import LabelObjectIn
from app.repositories.audit import AuditRepository
from app.repositories.labels import LabelRepository
from app.services.labelers.base import LabelerAdapter, LabelResult, Sample


class LabelingPipeline:
    def __init__(self, session: Session):
        self.session = session
        self.labels = LabelRepository(session)
        self.audit = AuditRepository(session)

    def run_sample(self, sample: Sample, adapters: Sequence[LabelerAdapter]) -> list[str]:
        """Run all adapters on a sample, persisting L1 rows. Returns created label ids."""
        created_ids: list[str] = []
        for adapter in adapters:
            result: LabelResult = adapter.run(sample)
            if result.status == L1Status.CREATED and result.payload is not None:
                row = self.labels.create_l1(result.payload, status=L1Status.CREATED)
                created_ids.append(row.label_id)
                self.audit.record(
                    entity_type="l1", entity_id=row.label_id, action="create", run_id=row.run_id
                )
            else:
                # Record a non-CREATED outcome (FAILED/SKIPPED) for auditability.
                placeholder = LabelObjectIn(
                    sample_id=sample.sample_id,
                    feature_id=sample.feature_id,
                    feature_version=sample.feature_version,
                    value={"error": result.error},
                    task_type=sample.task_type,
                    method=adapter.method,
                    method_ver=adapter.method_ver(),
                    inputs_hash=sample.inputs_hash(),
                    run_id=adapter.run_id,
                )
                row = self.labels.create_l1(placeholder, status=result.status)
                self.audit.record(
                    entity_type="l1",
                    entity_id=row.label_id,
                    action="failed",
                    run_id=row.run_id,
                    details={"status": result.status.value, "error": result.error},
                )
        return created_ids
