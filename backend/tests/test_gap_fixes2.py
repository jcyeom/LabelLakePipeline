"""Tests for 2순위 gap fixes (VERIFICATION_REPORT §5):
- B-G5: Gold rollback API (FR-8).
- B-G3: Dataset Builder applies task_type / label_method_filter / include_rationale (FR-9).
"""
from __future__ import annotations

from app.domain.enums import L1Status, LabelLevel, LabelMethod, Role
from app.domain.schemas import DatasetBuildRequest, LabelObjectIn
from app.repositories.audit import AuditRepository
from app.repositories.datasets import GoldVersionRepository
from app.repositories.labels import LabelRepository
from app.services.dataset import DatasetBuilder
from app.services.fusion import FusionService
from tests.conftest import l1_payload, submit_and_wait


def _seed_l1(session, sample_id, method, value, *, task_type="classification", rationale=None, mver="v1"):
    payload = LabelObjectIn(
        sample_id=sample_id,
        feature_id="f1",
        feature_version="fv1",
        value=value,
        task_type=task_type,
        method=method,
        method_ver=mver,
        confidence=0.9,
        rationale=rationale,
        inputs_hash="sha256:x",
        run_id="run-1",
    )
    return LabelRepository(session).create_l1(payload, status=L1Status.CREATED)


def _make_l2(session, sample_id, *, task_type="classification", rationale=None) -> str:
    """Seed agreeing rule+llm L1, fuse them into an L2, return its label_version."""
    _seed_l1(session, sample_id, LabelMethod.RULE, "x", task_type=task_type, rationale=rationale, mver="r1")
    _seed_l1(session, sample_id, LabelMethod.LLM, "x", task_type=task_type, rationale=rationale, mver="l1")
    session.flush()
    FusionService(session).run([sample_id])
    return LabelRepository(session).get_l2_by_sample(sample_id).label_version


# --------------------------------------------------------------- B-G5 rollback
def test_gold_rollback_reactivates_previous_version(client, auth):
    de, admin, viewer = auth(Role.DATA_ENGINEER), auth(Role.ADMIN), auth(Role.VIEWER)
    client.post("/api/v1/labels/l1", json=l1_payload(sample_id="gr", method="rule", method_ver="r1", value="x"), headers=de)
    client.post("/api/v1/labels/l1", json=l1_payload(sample_id="gr", method="llm", method_ver="l1", value="x"), headers=de)

    v1 = submit_and_wait(client, admin, "/api/v1/gold/republish", {"trigger": "t1"})["result"]
    v2 = submit_and_wait(client, admin, "/api/v1/gold/republish", {"trigger": "t2"})["result"]
    assert v1["version_id"] != v2["version_id"]

    rb = client.post(f"/api/v1/gold/rollback/{v1['version_id']}", headers=admin)
    assert rb.status_code == 200
    body = rb.json()
    assert body["is_active"] is True
    assert body["label_version"] == v1["label_version"]

    # Dashboard now reports the rolled-back version as the active gold version.
    dash = client.get("/api/v1/dashboard/metrics", headers=viewer).json()
    assert dash["gold_label_version"] == v1["label_version"]


def test_gold_rollback_unknown_version_404(client, auth):
    r = client.post("/api/v1/gold/rollback/nope-123", headers=auth(Role.ADMIN))
    assert r.status_code == 404


def test_gold_rollback_requires_admin(client, auth):
    r = client.post("/api/v1/gold/rollback/whatever", headers=auth(Role.DATA_ENGINEER))
    assert r.status_code == 403


# --------------------------------------------------------------- B-G3 options
def test_dataset_task_type_filter(db_session):
    lv = _make_l2(db_session, "d1", task_type="classification")
    builder = DatasetBuilder(db_session)
    excluded = builder.build(DatasetBuildRequest(feature_version="fv1", label_version=lv, task_type="regression"))
    assert excluded.sample_count == 0
    included = builder.build(DatasetBuildRequest(feature_version="fv1", label_version=lv, task_type="classification"))
    assert included.sample_count == 1


def test_dataset_method_filter(db_session):
    lv = _make_l2(db_session, "d2")
    builder = DatasetBuilder(db_session)
    excluded = builder.build(
        DatasetBuildRequest(feature_version="fv1", label_version=lv, label_method_filter=[LabelMethod.HUMAN])
    )
    assert excluded.sample_count == 0
    included = builder.build(
        DatasetBuildRequest(feature_version="fv1", label_version=lv, label_method_filter=[LabelMethod.RULE])
    )
    assert included.sample_count == 1


def test_dataset_include_rationale_recorded(db_session):
    lv = _make_l2(db_session, "d3", rationale={"reason": "because"})
    builder = DatasetBuilder(db_session)
    resp = builder.build(DatasetBuildRequest(feature_version="fv1", label_version=lv, include_rationale=True))
    audits = AuditRepository(db_session).by_entity("dataset", resp.dataset_id)
    assert audits and audits[0].details.get("rationale_count", 0) >= 1


def test_dataset_no_filter_includes_all(db_session):
    """Control: without task_type/method filters the sample is included."""
    lv = _make_l2(db_session, "d4")
    resp = DatasetBuilder(db_session).build(DatasetBuildRequest(feature_version="fv1", label_version=lv))
    assert resp.sample_count == 1
    # gold version repo sanity (rollback target source) — active version unaffected here.
    assert GoldVersionRepository(db_session).active() is None
