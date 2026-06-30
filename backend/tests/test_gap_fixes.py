"""Tests for 1순위 gap fixes (VERIFICATION_REPORT §4):
- B-G1: Human Review auto-routing for LLM parse failure & low confidence (PRD §5).
- B-G2: agreement_group_id grouping in fusion (FR-1/FR-4).
- F-G1: feature summary (feature_id/feature_version) exposed on the L1 view (§11.2).
"""
from __future__ import annotations

from app.domain.enums import L1Status, LabelMethod, Role
from app.domain.schemas import LabelObjectIn
from app.repositories.labels import LabelRepository
from app.repositories.reviews import ReviewRepository
from app.services.fusion import FusionService
from tests.conftest import l1_payload


def _seed(session, sample_id, method, value, conf, *, status=L1Status.CREATED, group=None, mver="v1"):
    payload = LabelObjectIn(
        sample_id=sample_id,
        feature_id="f1",
        feature_version="fv1",
        value=value,
        task_type="classification",
        method=method,
        method_ver=mver,
        confidence=conf,
        inputs_hash="sha256:x",
        run_id="run-1",
        agreement_group_id=group,
    )
    return LabelRepository(session).create_l1(payload, status=status)


# ----------------------------------------------------- B-G1: review auto-routing
def test_llm_parse_failure_routes_to_review(db_session):
    """A FAILED llm label routes the sample to review even if the rule label is fine."""
    _seed(db_session, "s1", LabelMethod.RULE, "high", 0.9)
    _seed(db_session, "s1", LabelMethod.LLM, {"error": "parse"}, None, status=L1Status.FAILED)
    db_session.flush()

    resp = FusionService(db_session).run(["s1"], low_confidence_threshold=0.0)
    assert resp.human_review_count == 1
    assert resp.created_l2_count == 0

    reviews = ReviewRepository(db_session).list()
    assert any("LLM_PARSE_FAILURE" in r.reason for r in reviews)


def test_all_failed_sample_routes_to_review_not_failed(db_session):
    """A sample with only a FAILED llm label is queued, not silently counted as failed."""
    _seed(db_session, "s2", LabelMethod.LLM, {"error": "x"}, None, status=L1Status.FAILED)
    db_session.flush()

    resp = FusionService(db_session).run(["s2"], low_confidence_threshold=0.0)
    assert resp.human_review_count == 1
    assert resp.failed_count == 0


def test_low_confidence_routes_to_review(db_session):
    """Agreeing but low-confidence labels are routed to review (§5)."""
    _seed(db_session, "s3", LabelMethod.RULE, "high", 0.3)
    _seed(db_session, "s3", LabelMethod.LLM, "high", 0.3)
    db_session.flush()

    resp = FusionService(db_session).run(["s3"], low_confidence_threshold=0.5)
    assert resp.human_review_count == 1
    assert resp.created_l2_count == 0
    reviews = ReviewRepository(db_session).list()
    assert any("LOW_CONFIDENCE" in r.reason for r in reviews)


def test_high_confidence_agreement_still_creates_l2(db_session):
    """Control: high-confidence agreement is NOT falsely routed to review."""
    _seed(db_session, "s4", LabelMethod.RULE, "high", 0.9)
    _seed(db_session, "s4", LabelMethod.LLM, "high", 0.9)
    db_session.flush()

    resp = FusionService(db_session).run(["s4"], low_confidence_threshold=0.5)
    assert resp.created_l2_count == 1
    assert resp.human_review_count == 0


# ----------------------------------------------------- B-G2: agreement grouping
def test_different_agreement_groups_fused_separately(db_session):
    """Two differing labels in DIFFERENT groups each form their own consensus → 2 L2, no review."""
    _seed(db_session, "s5", LabelMethod.RULE, "high", 0.9, group="g1")
    _seed(db_session, "s5", LabelMethod.LLM, "low", 0.9, group="g2")
    db_session.flush()

    resp = FusionService(db_session).run(["s5"], low_confidence_threshold=0.0)
    assert resp.created_l2_count == 2
    assert resp.human_review_count == 0


def test_same_agreement_group_disagreement_routes_to_review(db_session):
    """Two differing labels in the SAME group disagree → routed to review."""
    _seed(db_session, "s6", LabelMethod.RULE, "high", 0.9, group="g1")
    _seed(db_session, "s6", LabelMethod.LLM, "low", 0.9, group="g1")
    db_session.flush()

    resp = FusionService(db_session).run(["s6"], low_confidence_threshold=0.0)
    assert resp.human_review_count == 1
    assert resp.created_l2_count == 0


# ----------------------------------------------------- F-G1: feature summary
def test_l1_view_includes_feature_summary(client, auth):
    client.post("/api/v1/labels/l1", json=l1_payload(sample_id="sf1"), headers=auth(Role.DATA_ENGINEER))
    r = client.get("/api/v1/labels/l1", params={"sample_id": "sf1"}, headers=auth(Role.ML_ENGINEER))
    assert r.status_code == 200
    label = r.json()["labels"][0]
    assert label["feature_id"] == "feature-001"
    assert label["feature_version"] == "fv-2026-01"
