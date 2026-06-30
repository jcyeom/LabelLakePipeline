"""Shared enums — single source of truth (README §5, design SSOT).

These mirror the canonical enum dictionary in design/README.md §5 and are
imported by ORM models, Pydantic schemas, services and routers alike.
"""
from __future__ import annotations

from enum import Enum


class L1Status(str, Enum):
    CREATED = "CREATED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    INVALID = "INVALID"
    SUPERSEDED = "SUPERSEDED"


class L2Flag(str, Enum):
    AGREED = "agreed"
    SOFT_DISAGREEMENT = "soft_disagreement"
    HUMAN_REQUIRED = "human_required"


class L3Status(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class DriftStatus(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    REPUBLISH_REQUIRED = "REPUBLISH_REQUIRED"


class FusionPolicy(str, Enum):
    # Canonical Label Fusion Engine default — paper Algorithm 1 (논문 §3.3, 알고리즘 1):
    #   agree(L1) → consensus(agreed); elif confidence_gap(L1) > θ → argmax_conf(soft_disagreement);
    #   else → enqueue human (L2=NULL).
    CONFIDENCE_GAP = "confidence_gap"
    MAJORITY_VOTE = "majority_vote"
    CONFIDENCE_WEIGHTED = "confidence_weighted"
    RULE_PRIORITY = "rule_priority"
    HUMAN_PRIORITY = "human_priority"
    KAPPA_BASED = "kappa_based"
    CUSTOM_POLICY = "custom_policy"


class LabelLevel(str, Enum):
    L2 = "L2"
    L3 = "L3"
    L3_PRIORITY = "L3_PRIORITY"


class LabelMethod(str, Enum):
    RULE = "rule"
    LLM = "llm"
    HUMAN = "human"


class Role(str, Enum):
    ADMIN = "Admin"
    DATA_ENGINEER = "DataEngineer"
    ML_ENGINEER = "MLEngineer"
    REVIEWER = "Reviewer"
    VIEWER = "Viewer"


# Role hierarchy: higher index = more privilege (절차 12 RBAC).
ROLE_ORDER = [
    Role.VIEWER,
    Role.REVIEWER,
    Role.ML_ENGINEER,
    Role.DATA_ENGINEER,
    Role.ADMIN,
]


def role_at_least(actual: Role, required: Role) -> bool:
    """True if ``actual`` meets or exceeds ``required`` in the privilege order.

    Reviewer and MLEngineer are siblings in the PRD matrix; we treat the linear
    order as a coarse gate and let routers add explicit role checks where the
    matrix is non-linear (e.g. Reviewer-only review completion).
    """
    return ROLE_ORDER.index(actual) >= ROLE_ORDER.index(required)
