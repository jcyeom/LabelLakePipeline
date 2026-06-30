"""Tests for Gold Republish service (FR-8, §절차 9)."""
from __future__ import annotations

from app.domain.enums import Role
from app.repositories.datasets import GoldVersionRepository
from app.services.gold import GoldRepublishService
from app.domain.schemas import GoldRepublishRequest
from tests.conftest import l1_payload, submit_and_wait

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_agreeing_l1(client, auth, sample_id: str, value="high_risk") -> None:
    h = auth(Role.DATA_ENGINEER)
    r = client.post(
        "/api/v1/labels/l1",
        json=l1_payload(sample_id=sample_id, value=value, confidence=0.9),
        headers=h,
    )
    assert r.status_code == 201, r.text


def _republish(client, auth, sample_ids=None, trigger="test", fusion_policy="majority_vote") -> dict:
    body = {"trigger": trigger, "fusion_policy": fusion_policy}
    if sample_ids is not None:
        body["sample_ids"] = sample_ids
    run = submit_and_wait(client, auth(Role.ADMIN), "/api/v1/gold/republish", body)
    assert run["status"] == "COMPLETED", run
    return run["result"]


# ---------------------------------------------------------------------------
# FR-8: basic republish
# ---------------------------------------------------------------------------


def test_republish_returns_version_id_and_label_version(client, auth):
    """Republishing after seeding 2 agreeing samples returns a valid version_id
    and a label_version prefixed with 'lv-run-'."""
    _seed_agreeing_l1(client, auth, "sample-g01")
    _seed_agreeing_l1(client, auth, "sample-g02")

    body = _republish(client, auth, sample_ids=["sample-g01", "sample-g02"])

    assert "version_id" in body
    assert body["run_id"]
    assert body["label_version"].startswith("lv-run-")
    assert body["republished_count"] == 2


def test_republish_activates_new_gold_version(client, auth, db_session):
    """After republish the active gold version carries the new label_version."""
    _seed_agreeing_l1(client, auth, "sample-g03")
    _seed_agreeing_l1(client, auth, "sample-g04")

    resp = _republish(client, auth, sample_ids=["sample-g03", "sample-g04"])
    new_label_version = resp["label_version"]

    # Verify via GoldVersionRepository directly.
    gold_repo = GoldVersionRepository(db_session)
    active = gold_repo.active()
    assert active is not None
    assert active.label_version == new_label_version


def test_republish_active_version_reflected_in_dashboard(client, auth):
    """The dashboard metrics gold_label_version equals the newly republished version."""
    _seed_agreeing_l1(client, auth, "sample-g05")
    resp = _republish(client, auth, sample_ids=["sample-g05"])
    new_label_version = resp["label_version"]

    metrics = client.get(
        "/api/v1/dashboard/metrics",
        headers=auth(Role.VIEWER),
    )
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["gold_label_version"] == new_label_version


# ---------------------------------------------------------------------------
# FR-8: scoped republish with explicit sample_ids
# ---------------------------------------------------------------------------


def test_republish_with_explicit_sample_ids_scope(client, auth):
    """Providing sample_ids limits republished_count to the subset."""
    _seed_agreeing_l1(client, auth, "sample-g06")
    _seed_agreeing_l1(client, auth, "sample-g07")
    _seed_agreeing_l1(client, auth, "sample-g08")

    body = _republish(client, auth, sample_ids=["sample-g06", "sample-g07"])
    # Only the 2 specified samples are republished.
    assert body["republished_count"] == 2


# ---------------------------------------------------------------------------
# FR-8: rollback
# ---------------------------------------------------------------------------


def test_rollback_restores_previous_gold_version(db_session):
    """Rolling back to v1 makes v1 the active gold version again."""
    svc = GoldRepublishService(db_session)

    _seed_l1_direct(db_session, "sample-r01")
    _seed_l1_direct(db_session, "sample-r02")

    req1 = GoldRepublishRequest(
        trigger="initial",
        sample_ids=["sample-r01", "sample-r02"],
    )
    resp1 = svc.republish(req1, actor="tester")
    first_version_id = resp1.version_id

    _seed_l1_direct(db_session, "sample-r03")
    req2 = GoldRepublishRequest(
        trigger="second",
        sample_ids=["sample-r03"],
    )
    svc.republish(req2, actor="tester")

    # Active is now v2; confirm v1 is inactive.
    gold_repo = GoldVersionRepository(db_session)
    active_before = gold_repo.active()
    assert active_before.version_id != first_version_id

    # Rollback to v1.
    svc.rollback(first_version_id, actor="tester")

    active_after = gold_repo.active()
    assert active_after is not None
    assert active_after.version_id == first_version_id


# ---------------------------------------------------------------------------
# RBAC: DataEngineer is denied /gold/republish
# ---------------------------------------------------------------------------


def test_republish_data_engineer_role_returns_403(client, auth):
    """A DataEngineer calling POST /gold/republish receives 403."""
    r = client.post(
        "/api/v1/gold/republish",
        json={"trigger": "ci"},
        headers=auth(Role.DATA_ENGINEER),
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Internal helper — seed L1 directly (used in service-layer rollback test)
# ---------------------------------------------------------------------------


def _seed_l1_direct(session, sample_id: str) -> None:
    from app.domain.schemas import LabelObjectIn
    from app.domain.enums import LabelMethod
    from app.repositories.labels import LabelRepository

    repo = LabelRepository(session)
    repo.create_l1(
        LabelObjectIn(
            sample_id=sample_id,
            feature_id="feature-001",
            feature_version="fv-2026-01",
            value="high_risk",
            task_type="classification",
            method=LabelMethod.LLM,
            method_ver="llm-v2",
            confidence=0.9,
            inputs_hash="sha256:abc",
            run_id="run-001",
        )
    )
    session.flush()
