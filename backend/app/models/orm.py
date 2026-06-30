"""SQLAlchemy ORM models (design: db_design_prd.md §8 tables + 운영 테이블).

Generic column types (String/JSON/DateTime/Float) keep the schema portable across
SQLite (tests) and PostgreSQL 15 (prod). In production these map to the
partitioned / JSONB / array DDL defined in db_design_prd.md; here arrays are stored
as JSON lists and json columns as generic JSON.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LabelL1Candidate(Base):
    """Silver layer L1 candidate label — append-only (db_design_prd 절차 2, FR-2)."""

    __tablename__ = "labels_l1_candidate"
    # Composite indexes for the hot query paths (OPTIMIZATION_PLAN B):
    #   - drift distribution/anchor scans filter (method, method_ver, labeled_at)
    #   - get_l1_by_sample(active_only) filters (sample_id, status)
    __table_args__ = (
        Index("ix_l1_method_ver_time", "method", "method_ver", "labeled_at"),
        Index("ix_l1_sample_status", "sample_id", "status"),
    )

    label_id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    feature_id: Mapped[str] = mapped_column(String, nullable=False)
    feature_version: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String, index=True, nullable=False)
    method_ver: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rationale: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    inputs_hash: Mapped[str] = mapped_column(String, index=True, nullable=False)
    labeled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    agreement_group_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="CREATED")
    extra_metadata: Mapped[Optional[Any]] = mapped_column("metadata", JSON, nullable=True)


class LabelL2Consensus(Base):
    """Gold layer L2 consensus label (db_design_prd 절차 3, FR-4)."""

    __tablename__ = "labels_l2_consensus"
    # get_l2_by_sample: latest L2 per sample (sample_id, created_at DESC).
    __table_args__ = (Index("ix_l2_sample_created", "sample_id", "created_at"),)

    consensus_label_id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fusion_policy: Mapped[str] = mapped_column(String, nullable=False)
    fusion_version: Mapped[str] = mapped_column(String, nullable=False)
    source_l1_ids: Mapped[Any] = mapped_column(JSON, nullable=False)  # array
    agreement_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 논문 표 1 `agreement`: 다중 라벨러 raw 결과의 구조화 기록. 합의(L2) 시점에 채워진다.
    agreement: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)  # array of raw L1 records
    flag: Mapped[str] = mapped_column(String, nullable=False)
    fusion_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label_version: Mapped[str] = mapped_column(String, index=True, nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)


class LabelL3Gold(Base):
    """Gold layer L3 gold-standard label with version history (db_design_prd 절차 4, FR-6)."""

    __tablename__ = "labels_l3_gold"
    # get_l3_by_sample / get_active_l3_by_samples / anchor scans filter (sample_id, status).
    __table_args__ = (Index("ix_l3_sample_status", "sample_id", "status"),)

    gold_label_id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String, nullable=False)
    review_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_review_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    source_l1_ids: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)  # array
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    superseded_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class HumanReviewQueue(Base):
    """Human review queue (db_design_prd 절차 5, FR-5)."""

    __tablename__ = "human_review_queue"
    # pending_for_sample filters (sample_id, status); list orders (priority DESC, created_at).
    __table_args__ = (
        Index("ix_review_sample_status", "sample_id", "status"),
        Index("ix_review_priority_created", "priority", "created_at"),
    )

    review_id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    l1_label_ids: Mapped[Any] = mapped_column(JSON, nullable=False)  # array
    status: Mapped[str] = mapped_column(String, index=True, nullable=False, default="PENDING")
    assigned_to: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class LabelDriftMetric(Base):
    """Drift metric record (db_design_prd 절차 6, FR-7)."""

    __tablename__ = "label_drift_metrics"
    # list / latest_status_by_method order by (method, measured_at DESC).
    __table_args__ = (Index("ix_drift_method_time", "method", "measured_at"),)

    metric_id: Mapped[str] = mapped_column(String, primary_key=True)
    method: Mapped[str] = mapped_column(String, index=True, nullable=False)
    method_ver: Mapped[str] = mapped_column(String, nullable=False)
    baseline_window: Mapped[str] = mapped_column(String, nullable=False)
    current_window: Mapped[str] = mapped_column(String, nullable=False)
    psi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    kl_divergence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    anchor_accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DatasetManifest(Base):
    """Dataset manifest (db_design_prd 절차 7, FR-9)."""

    __tablename__ = "dataset_manifest"

    dataset_id: Mapped[str] = mapped_column(String, primary_key=True)
    feature_version: Mapped[str] = mapped_column(String, nullable=False)
    label_version: Mapped[str] = mapped_column(String, nullable=False)
    label_level: Mapped[str] = mapped_column(String, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    build_query: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_label_ids: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)  # array
    manifest_uri: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class LabelerRun(Base):
    """Labeler / fusion / job run registry (db_design_prd 절차 8, FR-10)."""

    __tablename__ = "labeler_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_type: Mapped[str] = mapped_column(String, nullable=False)  # labeler|fusion|drift|republish|dataset
    method: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    method_ver: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="RUNNING")
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    params: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    # Full job result (mirrors the legacy sync response body) for async run polling.
    result: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """Audit / lineage log (db_design_prd 절차 8, FR-10)."""

    __tablename__ = "audit_log"
    # by_entity lineage lookups order by created_at within (entity_type, entity_id).
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),)

    audit_id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    details: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GoldVersion(Base):
    """Gold republish version registry with rollback (db_design_prd 절차 8, FR-8)."""

    __tablename__ = "gold_versions"
    # active() filters is_active=1 (frequent: every fusion run / dashboard). Production
    # may swap this for a PG partial index (WHERE is_active) — see OPTIMIZATION_PLAN B.
    __table_args__ = (Index("ix_gold_active", "is_active"),)

    version_id: Mapped[str] = mapped_column(String, primary_key=True)
    label_version: Mapped[str] = mapped_column(String, nullable=False)
    fusion_policy: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    trigger: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
