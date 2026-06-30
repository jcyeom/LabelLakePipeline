"""Labeler adapter framework (backend_design_prd 절차 3, FR-3).

Common interface: ``LabelerAdapter.run(sample) -> LabelResult``. A new labeler type
extends the Label Object schema only via ``method`` / ``method_ver`` (NFR-1) — no
schema change required.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.domain.enums import L1Status, LabelMethod
from app.domain.schemas import LabelObjectIn, Value
from app.util import sha256_hash


@dataclass
class Sample:
    """Input to a labeler: a sample and its feature payload."""

    sample_id: str
    feature_id: str
    feature_version: str
    features: dict = field(default_factory=dict)
    task_type: str = "classification"

    def inputs_hash(self) -> str:
        return sha256_hash(self.features)


@dataclass
class LabelResult:
    """Adapter output. ``payload`` is None when ``status`` is FAILED/SKIPPED."""

    status: L1Status
    payload: Optional[LabelObjectIn] = None
    error: Optional[str] = None


class LabelerAdapter(ABC):
    method: LabelMethod

    def __init__(self, run_id: str):
        self.run_id = run_id

    @abstractmethod
    def method_ver(self) -> str:
        """Identifier capturing the exact labeler configuration (rule id, model+prompt
        hash, reviewer id). Changing prompt/model MUST change this (FR-3 수용 기준)."""

    @abstractmethod
    def run(self, sample: Sample) -> LabelResult:  # pragma: no cover - interface
        ...

    def _build(
        self,
        sample: Sample,
        value: Value,
        *,
        confidence: Optional[float] = None,
        rationale=None,
        metadata=None,
    ) -> LabelObjectIn:
        return LabelObjectIn(
            sample_id=sample.sample_id,
            feature_id=sample.feature_id,
            feature_version=sample.feature_version,
            value=value,
            task_type=sample.task_type,
            method=self.method,
            method_ver=self.method_ver(),
            confidence=confidence,
            rationale=rationale,
            inputs_hash=sample.inputs_hash(),
            run_id=self.run_id,
            metadata=metadata,
        )
