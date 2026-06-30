"""Gold Republish service (backend_design_prd 절차 9, FR-8).

Creates a new active gold version, then re-runs fusion over the requested scope so the
new L2 rows carry the new ``label_version``. Previous versions remain for rollback.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.domain.enums import FusionPolicy
from app.domain.schemas import GoldRepublishRequest, GoldRepublishResponse
from app.repositories.audit import AuditRepository
from app.repositories.datasets import GoldVersionRepository
from app.repositories.labels import LabelRepository
from app.repositories.runs import RunRepository
from app.services.fusion import FusionService


class GoldRepublishService:
    def __init__(self, session: Session):
        self.session = session
        self.gold = GoldVersionRepository(session)
        self.runs = RunRepository(session)
        self.audit = AuditRepository(session)
        self.labels = LabelRepository(session)

    def _all_sample_ids(self) -> list[str]:
        return self.labels.all_sample_ids()

    def republish(
        self, req: GoldRepublishRequest, *, actor: Optional[str] = None, run_id: Optional[str] = None
    ) -> GoldRepublishResponse:
        policy = req.fusion_policy or FusionPolicy.CONFIDENCE_GAP
        sample_ids = req.sample_ids or self._all_sample_ids()

        run = self.runs.get(run_id) if run_id else None
        if run is None:
            run = self.runs.start("republish", params={"trigger": req.trigger, "policy": policy.value})
        label_version = f"lv-{run.run_id}"

        # Activate a new gold version *before* fusion so FusionService stamps L2 with it.
        version = self.gold.create(
            label_version=label_version,
            fusion_policy=policy.value,
            trigger=req.trigger,
            scope=req.sample_ids,
            run_id=run.run_id,
            activate=True,
        )
        # Nested fusion: reuse the republish run id and don't emit a separate 'fusion'
        # run record (avoids a phantom run + double finish on the registry).
        fusion = FusionService(self.session)
        result = fusion.run(sample_ids, policy=policy, actor=actor, run_id=run.run_id, record_run=False)

        self.runs.finish(run.run_id, created_count=result.created_l2_count)
        self.audit.record(
            entity_type="gold_version",
            entity_id=version.version_id,
            action="republish",
            actor=actor,
            run_id=run.run_id,
            details={"trigger": req.trigger, "label_version": label_version},
        )
        return GoldRepublishResponse(
            version_id=version.version_id,
            run_id=run.run_id,
            label_version=label_version,
            republished_count=result.created_l2_count,
        )

    def rollback(self, version_id: str, *, actor: Optional[str] = None):
        version = self.gold.rollback_to(version_id)
        if version is not None:
            self.audit.record(
                entity_type="gold_version", entity_id=version_id, action="rollback", actor=actor
            )
        return version
