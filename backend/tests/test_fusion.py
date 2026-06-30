"""Tests for the Label Fusion engine & API (FR-4, AC-2, §10.2)."""
from __future__ import annotations

from app.domain.enums import FusionPolicy, L2Flag, Role
from app.domain.schemas import LabelObjectIn
from app.repositories.labels import LabelRepository
from app.services.fusion import FusionEngine
from tests.conftest import l1_payload, submit_and_wait


def _make_l1(repo: LabelRepository, **overrides):
    """Seed one L1 ORM row via the repository and return it."""
    payload = LabelObjectIn(**l1_payload(**overrides))
    return repo.create_l1(payload)


# --------------------------------------------------------------- engine-level
def test_unanimous_values_are_agreed(db_session):
    repo = LabelRepository(db_session)
    a = _make_l1(repo, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.8)
    b = _make_l1(repo, method="rule", method_ver="rule-v1", value="high_risk", confidence=0.7)

    decision = FusionEngine().decide([a, b], policy=FusionPolicy.MAJORITY_VOTE)

    assert decision.human_review_required is False
    assert decision.flag == L2Flag.AGREED
    assert decision.agreement_score == 1.0
    assert decision.value == "high_risk"


def test_majority_vote_tie_requires_human(db_session):
    repo = LabelRepository(db_session)
    a = _make_l1(repo, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.8)
    b = _make_l1(repo, method="rule", method_ver="rule-v1", value="low_risk", confidence=0.7)

    decision = FusionEngine().decide([a, b], policy=FusionPolicy.MAJORITY_VOTE)

    assert decision.human_review_required is True
    assert decision.flag == L2Flag.HUMAN_REQUIRED


def test_single_label_is_agreed_single_labeler(db_session):
    repo = LabelRepository(db_session)
    a = _make_l1(repo, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.8)

    decision = FusionEngine().decide([a], policy=FusionPolicy.MAJORITY_VOTE)

    assert decision.human_review_required is False
    assert decision.flag == L2Flag.AGREED
    assert decision.reason == "single_labeler"


def test_confidence_weighted_picks_high_confidence_value(db_session):
    repo = LabelRepository(db_session)
    a = _make_l1(repo, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.9)
    b = _make_l1(repo, method="rule", method_ver="rule-v1", value="low_risk", confidence=0.1)

    decision = FusionEngine().decide([a, b], policy=FusionPolicy.CONFIDENCE_WEIGHTED)

    assert decision.human_review_required is False
    assert decision.value == "high_risk"


def test_confidence_weighted_near_equal_requires_human(db_session):
    repo = LabelRepository(db_session)
    a = _make_l1(repo, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.5)
    b = _make_l1(repo, method="rule", method_ver="rule-v1", value="low_risk", confidence=0.45)

    decision = FusionEngine().decide([a, b], policy=FusionPolicy.CONFIDENCE_WEIGHTED)

    assert decision.human_review_required is True
    assert decision.flag == L2Flag.HUMAN_REQUIRED


def test_rule_priority_prefers_rule_method_value(db_session):
    repo = LabelRepository(db_session)
    a = _make_l1(repo, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.95)
    b = _make_l1(repo, method="rule", method_ver="rule-v1", value="low_risk", confidence=0.3)

    decision = FusionEngine().decide([a, b], policy=FusionPolicy.RULE_PRIORITY)

    assert decision.human_review_required is False
    assert decision.value == "low_risk"


# ------------------------------------------------------------------ API-level
def _seed_l1_api(client, auth, *, sample_id, method, method_ver, value, confidence):
    return client.post(
        "/api/v1/labels/l1",
        json=l1_payload(
            sample_id=sample_id, method=method, method_ver=method_ver, value=value, confidence=confidence
        ),
        headers=auth(Role.DATA_ENGINEER),
    )


def test_fusion_run_creates_l2_and_review(client, auth):
    # sample-A: agreeing pair -> L2; sample-B: disagreeing pair -> review queue.
    _seed_l1_api(client, auth, sample_id="sample-A", method="llm", method_ver="llm-v1", value="high_risk", confidence=0.8)
    _seed_l1_api(client, auth, sample_id="sample-A", method="rule", method_ver="rule-v1", value="high_risk", confidence=0.7)
    _seed_l1_api(client, auth, sample_id="sample-B", method="llm", method_ver="llm-v1", value="high_risk", confidence=0.8)
    _seed_l1_api(client, auth, sample_id="sample-B", method="rule", method_ver="rule-v1", value="low_risk", confidence=0.7)

    run = submit_and_wait(
        client,
        auth(Role.DATA_ENGINEER),
        "/api/v1/fusion/run",
        {"sample_ids": ["sample-A", "sample-B"], "fusion_policy": "majority_vote"},
    )
    assert run["status"] == "COMPLETED"
    body = run["result"]
    assert body["created_l2_count"] == 1
    assert body["human_review_count"] == 1

    # AC-2: L2 for sample-A carries source_l1_ids and fusion_policy.
    l2 = client.get("/api/v1/labels/l2", params={"sample_id": "sample-A"}, headers=auth(Role.ML_ENGINEER))
    assert l2.status_code == 200, l2.text
    l2_body = l2.json()
    assert l2_body["fusion_policy"] == "majority_vote"
    assert len(l2_body["source_l1_ids"]) == 2

    # sample-B routed to a pending review.
    reviews = client.get("/api/v1/reviews", params={"status": "PENDING"}, headers=auth(Role.REVIEWER))
    assert reviews.status_code == 200, reviews.text
    pending = reviews.json()["reviews"]
    assert any(rv["sample_id"] == "sample-B" for rv in pending)


def test_fusion_run_no_l1_increments_failed(client, auth):
    run = submit_and_wait(
        client,
        auth(Role.DATA_ENGINEER),
        "/api/v1/fusion/run",
        {"sample_ids": ["sample-empty"], "fusion_policy": "majority_vote"},
    )
    body = run["result"]
    assert body["failed_count"] == 1
    assert body["created_l2_count"] == 0


def test_fusion_run_rbac_viewer_forbidden(client, auth):
    r = client.post(
        "/api/v1/fusion/run",
        json={"sample_ids": ["sample-A"], "fusion_policy": "majority_vote"},
        headers=auth(Role.VIEWER),
    )
    assert r.status_code == 403
