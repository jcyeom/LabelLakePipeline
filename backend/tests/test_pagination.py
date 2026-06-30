"""Pagination behaviour for list/search endpoints (limit/offset windowing).

Covers app/api/pagination.py + the limit/offset paths threaded through the reviews,
labels/search, drift/metrics and audit/lineage endpoints.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.enums import Role
from app.models.orm import LabelDriftMetric
from app.util import new_id, now_utc
from tests.conftest import l1_payload


# ----------------------------------------------------------------- reviews
def _seed_reviews(client, auth, n):
    de = auth(Role.DATA_ENGINEER)
    for i in range(n):
        client.post(
            "/api/v1/reviews",
            json={"sample_id": f"pg-{i}", "reason": "r", "priority": i, "l1_label_ids": []},
            headers=de,
        )


def test_reviews_limit_offset_windows_are_disjoint(client, auth):
    _seed_reviews(client, auth, 5)
    rv = auth(Role.REVIEWER)
    page1 = client.get("/api/v1/reviews", params={"limit": 2, "offset": 0}, headers=rv).json()["reviews"]
    page2 = client.get("/api/v1/reviews", params={"limit": 2, "offset": 2}, headers=rv).json()["reviews"]
    assert len(page1) == 2
    assert len(page2) == 2
    assert {r["review_id"] for r in page1}.isdisjoint({r["review_id"] for r in page2})


def test_reviews_limit_below_min_is_422(client, auth):
    r = client.get("/api/v1/reviews", params={"limit": 0}, headers=auth(Role.REVIEWER))
    assert r.status_code == 422
    assert r.json()["error_code"] == "VALIDATION_ERROR"


def test_reviews_limit_above_max_is_422(client, auth):
    r = client.get("/api/v1/reviews", params={"limit": 99999}, headers=auth(Role.REVIEWER))
    assert r.status_code == 422


def test_reviews_default_page_returns_all_when_under_limit(client, auth):
    _seed_reviews(client, auth, 3)
    rows = client.get("/api/v1/reviews", headers=auth(Role.REVIEWER)).json()["reviews"]
    assert len(rows) == 3  # default limit (50) covers all


# ----------------------------------------------------------------- labels/search
def test_labels_search_by_run_id_is_paginated(client, auth):
    de = auth(Role.DATA_ENGINEER)
    for i in range(4):
        client.post(
            "/api/v1/labels/l1",
            json=l1_payload(sample_id=f"srch-{i}", run_id="run-pg", method_ver=f"mv-{i}"),
            headers=de,
        )
    me = auth(Role.ML_ENGINEER)
    first = client.get("/api/v1/labels/search", params={"run_id": "run-pg", "limit": 2, "offset": 0}, headers=me).json()
    second = client.get("/api/v1/labels/search", params={"run_id": "run-pg", "limit": 2, "offset": 2}, headers=me).json()
    assert first["count"] == 2
    assert second["count"] == 2
    ids1 = {r["label_id"] for r in first["labels"]}
    ids2 = {r["label_id"] for r in second["labels"]}
    assert ids1.isdisjoint(ids2)


# ----------------------------------------------------------------- drift/metrics
def test_drift_metrics_respects_limit(client, auth, db_session):
    for i in range(4):
        db_session.add(LabelDriftMetric(
            metric_id=new_id("drift"), method="llm", method_ver="v1",
            baseline_window="b", current_window="c", psi=0.1, kl_divergence=0.1,
            anchor_accuracy=None, status="NORMAL",
            measured_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
        ))
    db_session.commit()

    rows = client.get("/api/v1/drift/metrics", params={"limit": 2}, headers=auth(Role.VIEWER)).json()
    assert len(rows) == 2


# ----------------------------------------------------------------- audit/lineage
def test_audit_lineage_respects_limit(client, auth, db_session):
    from app.repositories.audit import AuditRepository

    repo = AuditRepository(db_session)
    for i in range(5):
        repo.record(entity_type="l1", entity_id="ent-pg", action=f"a{i}")
    db_session.commit()

    body = client.get(
        "/api/v1/audit/lineage", params={"entity_id": "ent-pg", "limit": 3}, headers=auth(Role.DATA_ENGINEER)
    ).json()
    assert len(body["records"]) == 3
