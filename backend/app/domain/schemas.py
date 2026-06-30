"""Pydantic v2 schemas — API contract (design: backend_design_prd, README §4/§6).

Field sets mirror the canonical Label Object (README §4) and the §9 API specs.
``Value`` is ``dict | str | float | int`` per task_type, stored as JSON.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    DriftStatus,
    FusionPolicy,
    L1Status,
    L2Flag,
    L3Status,
    LabelLevel,
    LabelMethod,
    ReviewStatus,
)

Value = Union[dict, str, float, int]


# ---------------------------------------------------------------- Label Object
class LabelObjectIn(BaseModel):
    """L1 create request (POST /api/v1/labels/l1, FR-1/FR-2)."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    feature_id: str
    feature_version: str
    value: Value
    task_type: str
    method: LabelMethod
    method_ver: str = Field(..., min_length=1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rationale: Optional[Union[dict, str]] = None
    inputs_hash: str = Field(..., min_length=1)
    labeled_at: Optional[datetime] = None
    run_id: str = Field(..., min_length=1)
    agreement_group_id: Optional[str] = None
    metadata: Optional[dict] = None


class LabelL1Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label_id: str
    status: L1Status


class L1LabelView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label_id: str
    method: LabelMethod
    method_ver: str
    value: Value
    confidence: Optional[float] = None
    rationale: Optional[Union[dict, str]] = None
    feature_id: Optional[str] = None
    feature_version: Optional[str] = None
    inputs_hash: Optional[str] = None
    run_id: Optional[str] = None
    status: L1Status
    labeled_at: Optional[datetime] = None


class L1ListResponse(BaseModel):
    sample_id: str
    labels: list[L1LabelView]


class L1RecordView(L1LabelView):
    """L1 view that also carries sample_id, for cross-sample search (FR-2/FR-10)."""

    sample_id: str


class L1SearchResponse(BaseModel):
    count: int
    labels: list[L1RecordView]


# ---------------------------------------------------------------- L2 / L3 views
class L2View(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    consensus_label_id: str
    sample_id: str
    value: Value
    confidence: Optional[float] = None
    fusion_policy: str
    flag: L2Flag
    agreement_score: Optional[float] = None
    # 논문 표 1 `agreement`: 다중 라벨러 raw 결과의 구조화 기록.
    agreement: Optional[list[dict]] = None
    source_l1_ids: list[str]
    fusion_reason: Optional[str] = None
    label_version: str


class L3View(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gold_label_id: str
    sample_id: str
    value: Value
    reviewer_id: str
    review_reason: Optional[str] = None
    status: L3Status
    label_version: str


# ---------------------------------------------------------------- Fusion
class FusionRunRequest(BaseModel):
    sample_ids: list[str] = Field(..., min_length=1)
    # Canonical default = paper Algorithm 1 (논문 §3.3, 알고리즘 1).
    fusion_policy: FusionPolicy = FusionPolicy.CONFIDENCE_GAP
    confidence_gap_threshold: float = 0.15
    disagreement_threshold: float = 0.4
    low_confidence_threshold: float = 0.5


class FusionRunResponse(BaseModel):
    run_id: str
    created_l2_count: int
    human_review_count: int
    failed_count: int


# ---------------------------------------------------------------- Reviews
class ReviewCreateRequest(BaseModel):
    sample_id: str
    reason: str
    priority: int = 0
    l1_label_ids: list[str] = Field(default_factory=list)


class ReviewCreateResponse(BaseModel):
    review_id: str
    status: ReviewStatus


class ReviewView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    review_id: str
    sample_id: str
    reason: str
    priority: int
    l1_label_ids: list[str]
    status: ReviewStatus
    assigned_to: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class ReviewListResponse(BaseModel):
    reviews: list[ReviewView]


class ReviewCompleteRequest(BaseModel):
    value: Value
    reviewer_id: str
    review_reason: Optional[str] = None
    regenerate_l2: bool = True


class ReviewCompleteResponse(BaseModel):
    gold_label_id: str
    status: ReviewStatus


# ---------------------------------------------------------------- Drift
class DriftRunRequest(BaseModel):
    method: LabelMethod
    method_ver: str
    baseline_window: str
    current_window: str
    metrics: list[str] = Field(default_factory=lambda: ["psi", "kl_divergence", "anchor_accuracy"])


class DriftRunResponse(BaseModel):
    metric_id: str
    psi: Optional[float] = None
    kl_divergence: Optional[float] = None
    anchor_accuracy: Optional[float] = None
    anchor_accuracy_drop: Optional[float] = None  # 직전 측정 대비 하락폭 (B-G4, §7)
    status: DriftStatus


class DriftMetricView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_id: str
    method: str
    method_ver: str
    baseline_window: str
    current_window: str
    psi: Optional[float] = None
    kl_divergence: Optional[float] = None
    anchor_accuracy: Optional[float] = None
    status: DriftStatus
    measured_at: datetime


# ---------------------------------------------------------------- Datasets
class DatasetBuildRequest(BaseModel):
    feature_version: str
    label_version: str
    label_level: LabelLevel = LabelLevel.L2
    task_type: Optional[str] = None
    confidence_min: Optional[float] = None
    exclude_disagreement: bool = False
    label_method_filter: Optional[list[LabelMethod]] = None
    include_rationale: bool = False


class DatasetBuildResponse(BaseModel):
    dataset_id: str
    sample_count: int
    manifest_uri: str


# ---------------------------------------------------------------- Gold republish
class GoldRepublishRequest(BaseModel):
    trigger: str
    fusion_policy: Optional[FusionPolicy] = None
    sample_ids: Optional[list[str]] = None  # None => full scope


class GoldRepublishResponse(BaseModel):
    version_id: str
    run_id: str
    label_version: str
    republished_count: int


class GoldRollbackResponse(BaseModel):
    version_id: str
    label_version: str
    is_active: bool


# ---------------------------------------------------------------- Runs
class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    run_type: str
    method: Optional[str] = None
    method_ver: Optional[str] = None
    status: str
    created_count: int
    failed_count: int
    params: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None


class RunAcceptedResponse(BaseModel):
    """202 response for an async batch job; poll GET /api/v1/runs/{run_id}."""

    run_id: str
    status: str = "accepted"
    poll_url: str


# ---------------------------------------------------------------- Audit / lineage
class LineageResponse(BaseModel):
    entity_type: str
    entity_id: str
    records: list[dict[str, Any]]


# ---------------------------------------------------------------- Alerts
class AlertView(BaseModel):
    alert_id: str
    severity: str
    source: str
    message: str
    details: Optional[Any] = None
    created_at: Optional[str] = None


class AlertListResponse(BaseModel):
    count: int
    alerts: list[AlertView]


# ---------------------------------------------------------------- Dashboard
class DashboardMetrics(BaseModel):
    total_l1: int
    l1_by_method: dict[str, int]
    failure_rate_by_method: dict[str, float]
    avg_confidence_by_method: dict[str, float]
    l2_agreement_rate: float
    human_review_queue_size: int
    l3_count: int
    drift_status_by_method: dict[str, str]
    gold_label_version: Optional[str] = None


# ---------------------------------------------------------------- Errors
class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: Optional[Any] = None
