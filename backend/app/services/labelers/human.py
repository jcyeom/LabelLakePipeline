"""Human labeler adapter (FR-3 Human Labeler). Produces L3-capable label objects."""
from __future__ import annotations

from typing import Optional

from app.domain.enums import L1Status, LabelMethod
from app.services.labelers.base import LabelerAdapter, LabelResult, Sample


class HumanLabeler(LabelerAdapter):
    method = LabelMethod.HUMAN

    def __init__(self, run_id: str, reviewer_id: str):
        super().__init__(run_id)
        self.reviewer_id = reviewer_id

    def method_ver(self) -> str:
        return f"human:{self.reviewer_id}"

    def label(self, sample: Sample, value, *, comment: Optional[str] = None) -> LabelResult:
        payload = self._build(
            sample,
            value,
            confidence=1.0,
            rationale={"reviewer_id": self.reviewer_id, "comment": comment},
            metadata={"reviewer_id": self.reviewer_id},
        )
        return LabelResult(status=L1Status.CREATED, payload=payload)

    def run(self, sample: Sample) -> LabelResult:
        # A human label requires an explicit value; ``label`` is the real entry point.
        return LabelResult(status=L1Status.SKIPPED, error="human labels require explicit value via label()")
