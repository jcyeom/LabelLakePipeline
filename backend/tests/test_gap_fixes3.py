"""Tests for 3순위 gap fixes (VERIFICATION_REPORT §4 잔여):
- B-G6: label lineage search by run_id / method_ver.
- F-G5: single review fetch GET /reviews/{id}.
- B-G7: alert events (GET /alerts) + drift-triggered re-review routing (§5).
- B-G8: REPUBLISH_REQUIRED reachable (covered in test_drift; routing asserted here).
- AC-4: dataset build reproducibility.
"""
from __future__ import annotations

from app.domain.enums import DriftStatus, LabelMethod, Role
from app.domain.schemas import DatasetBuildRequest, DriftRunRequest
from app.repositories.audit import AuditRepository
from app.repositories.datasets import DatasetRepository
from app.repositories.drift import DriftRepository
from app.repositories.reviews import ReviewRepository
from app.services.dataset import DatasetBuilder
from app.services.drift import DriftService
from tests.conftest import l1_payload
from tests.test_drift import (
    BASELINE_WINDOW,
    CURRENT_WINDOW,
    _METHOD,
    _METHOD_VER,
    _dt,
    _seed_l1 as drift_l1,
    _seed_l3 as drift_l3,
)
from tests.test_gap_fixes2 import _make_l2


# --------------------------------------------------------------- B-G6 search
def test_label_search_by_run_id(client, auth):
    de, ml = auth(Role.DATA_ENGINEER), auth(Role.ML_ENGINEER)
    client.post("/api/v1/labels/l1", json=l1_payload(sample_id="a", run_id="runX", method="rule", method_ver="rv"), headers=de)
    client.post("/api/v1/labels/l1", json=l1_payload(sample_id="b", run_id="runX", method="llm", method_ver="lv"), headers=de)
    client.post("/api/v1/labels/l1", json=l1_payload(sample_id="c", run_id="other", method="rule", method_ver="rv"), headers=de)

    r = client.get("/api/v1/labels/search", params={"run_id": "runX"}, headers=ml)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert {x["sample_id"] for x in body["labels"]} == {"a", "b"}


def test_label_search_by_method_ver(client, auth):
    de, ml = auth(Role.DATA_ENGINEER), auth(Role.ML_ENGINEER)
    client.post("/api/v1/labels/l1", json=l1_payload(sample_id="a", method_ver="mvX", run_id="r1"), headers=de)
    client.post("/api/v1/labels/l1", json=l1_payload(sample_id="b", method_ver="mvY", run_id="r1"), headers=de)
    r = client.get("/api/v1/labels/search", params={"method_ver": "mvX"}, headers=ml)
    assert r.json()["count"] == 1
    assert r.json()["labels"][0]["method_ver"] == "mvX"


def test_label_search_requires_filter(client, auth):
    r = client.get("/api/v1/labels/search", headers=auth(Role.ML_ENGINEER))
    assert r.status_code == 422


def test_label_search_rbac(client, auth):
    r = client.get("/api/v1/labels/search", params={"run_id": "x"}, headers=auth(Role.VIEWER))
    assert r.status_code == 403


# --------------------------------------------------------------- F-G5 single review
def test_get_single_review(client, auth):
    created = client.post(
        "/api/v1/reviews",
        json={"sample_id": "s", "reason": "R", "priority": 3, "l1_label_ids": []},
        headers=auth(Role.DATA_ENGINEER),
    ).json()
    rid = created["review_id"]
    r = client.get(f"/api/v1/reviews/{rid}", headers=auth(Role.REVIEWER))
    assert r.status_code == 200
    assert r.json()["review_id"] == rid
    assert r.json()["sample_id"] == "s"


def test_get_single_review_404(client, auth):
    assert client.get("/api/v1/reviews/none", headers=auth(Role.REVIEWER)).status_code == 404


def test_get_single_review_rbac(client, auth):
    assert client.get("/api/v1/reviews/none", headers=auth(Role.VIEWER)).status_code == 403


# --------------------------------------------------------------- B-G7 alerts + routing
def test_alerts_endpoint_lists_recorded_alerts(client, auth, session_factory):
    s = session_factory()
    AuditRepository(s).record_alert(severity="CRITICAL", source="test", message="boom")
    s.commit()
    s.close()
    r = client.get("/api/v1/alerts", headers=auth(Role.VIEWER))
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["alerts"][0]["severity"] == "CRITICAL"
    assert body["alerts"][0]["message"] == "boom"


def test_drift_republish_emits_alert_and_routes_anchor_to_review(db_session):
    # prior anchor accuracy 1.0; current collapses to 0.0 → drop 1.0 → REPUBLISH_REQUIRED
    DriftRepository(db_session).create(
        method=_METHOD,
        method_ver=_METHOD_VER,
        baseline_window=BASELINE_WINDOW,
        current_window=CURRENT_WINDOW,
        psi=None,
        kl_divergence=None,
        anchor_accuracy=1.0,
        status="NORMAL",
    )
    sid = "drift-route-sample"
    drift_l3(db_session, sid, "high_risk")
    drift_l1(db_session, "low_risk", _dt("2026-02-15T00:00:00"), sample_id=sid)
    db_session.commit()

    resp = DriftService(db_session).run(
        DriftRunRequest(
            method=LabelMethod.LLM,
            method_ver=_METHOD_VER,
            baseline_window=BASELINE_WINDOW,
            current_window=CURRENT_WINDOW,
            metrics=["anchor_accuracy"],
        )
    )
    assert resp.status == DriftStatus.REPUBLISH_REQUIRED

    alerts = AuditRepository(db_session).list_alerts()
    assert any(a.action == "REPUBLISH_REQUIRED" for a in alerts)

    reviews = ReviewRepository(db_session).list()
    assert any(r.reason == "DRIFT_REVIEW" and r.sample_id == sid for r in reviews)


# --------------------------------------------------------------- AC-4 reproducibility
def test_dataset_build_is_reproducible(db_session):
    lv = _make_l2(db_session, "rep1")
    builder = DatasetBuilder(db_session)
    req = DatasetBuildRequest(feature_version="fv1", label_version=lv)
    r1 = builder.build(req)
    r2 = builder.build(req)

    repo = DatasetRepository(db_session)
    m1, m2 = repo.get(r1.dataset_id), repo.get(r2.dataset_id)
    assert r1.sample_count == r2.sample_count == 1
    assert m1.source_label_ids == m2.source_label_ids
    assert m1.build_query == m2.build_query
