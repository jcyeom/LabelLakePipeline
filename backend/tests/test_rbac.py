"""Tests for §12 RBAC permission matrix (cross-cutting).

Parametrized over each endpoint with under-privileged and sufficient roles.
Under-privileged → 403; sufficient → anything but 403 (200/201/404/422 all OK).
"""
from __future__ import annotations

import pytest

from app.domain.enums import Role
from tests.conftest import l1_payload

# ---------------------------------------------------------------------------
# Minimal request bodies for each endpoint that requires one
# ---------------------------------------------------------------------------

_FUSION_BODY = {
    "sample_ids": ["sample-001"],
    "fusion_policy": "majority_vote",
}

_REVIEW_CREATE_BODY = {
    "sample_id": "sample-001",
    "reason": "test disagreement",
    "priority": 0,
    "l1_label_ids": [],
}

_REVIEW_COMPLETE_BODY = {
    "value": "high_risk",
    "reviewer_id": "tester",
    "review_reason": "looks correct",
    "regenerate_l2": False,
}

_DRIFT_BODY = {
    "method": "llm",
    "method_ver": "llm-v2",
    "baseline_window": "2026-01-01/2026-01-15",
    "current_window": "2026-01-16/2026-01-31",
    "metrics": ["psi"],
}

_DATASET_BODY = {
    "feature_version": "fv-2026-01",
    "label_version": "lv-2026-01",
    "label_level": "L2",
}

_GOLD_BODY = {
    "trigger": "manual",
}

_DUMMY_REVIEW_ID = "review-does-not-exist-00000"


# ---------------------------------------------------------------------------
# POST /api/v1/labels/l1 — DataEngineer+
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [Role.VIEWER, Role.ML_ENGINEER])
def test_post_l1_under_privileged_gets_403(client, auth, role):
    r = client.post("/api/v1/labels/l1", json=l1_payload(), headers=auth(role))
    assert r.status_code == 403, f"expected 403 for {role}, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.DATA_ENGINEER, Role.ADMIN])
def test_post_l1_sufficient_role_not_403(client, auth, role):
    r = client.post("/api/v1/labels/l1", json=l1_payload(), headers=auth(role))
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# GET /api/v1/labels/l1 — MLEngineer+
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [Role.VIEWER, Role.REVIEWER])
def test_get_l1_under_privileged_gets_403(client, auth, role):
    r = client.get("/api/v1/labels/l1", params={"sample_id": "sample-001"}, headers=auth(role))
    assert r.status_code == 403, f"expected 403 for {role}, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.ML_ENGINEER, Role.DATA_ENGINEER, Role.ADMIN])
def test_get_l1_sufficient_role_not_403(client, auth, role):
    r = client.get("/api/v1/labels/l1", params={"sample_id": "sample-001"}, headers=auth(role))
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# POST /api/v1/fusion/run — DataEngineer+
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [Role.VIEWER, Role.REVIEWER, Role.ML_ENGINEER])
def test_post_fusion_run_under_privileged_gets_403(client, auth, role):
    r = client.post("/api/v1/fusion/run", json=_FUSION_BODY, headers=auth(role))
    assert r.status_code == 403, f"expected 403 for {role}, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.DATA_ENGINEER, Role.ADMIN])
def test_post_fusion_run_sufficient_role_not_403(client, auth, role):
    r = client.post("/api/v1/fusion/run", json=_FUSION_BODY, headers=auth(role))
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# GET /api/v1/reviews — Reviewer+
# ---------------------------------------------------------------------------

def test_get_reviews_viewer_gets_403(client, auth):
    r = client.get("/api/v1/reviews", headers=auth(Role.VIEWER))
    assert r.status_code == 403, f"expected 403 for Viewer, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ML_ENGINEER, Role.DATA_ENGINEER, Role.ADMIN])
def test_get_reviews_sufficient_role_not_403(client, auth, role):
    r = client.get("/api/v1/reviews", headers=auth(role))
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# POST /api/v1/reviews — DataEngineer+
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [Role.VIEWER, Role.REVIEWER, Role.ML_ENGINEER])
def test_post_reviews_under_privileged_gets_403(client, auth, role):
    r = client.post("/api/v1/reviews", json=_REVIEW_CREATE_BODY, headers=auth(role))
    assert r.status_code == 403, f"expected 403 for {role}, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.DATA_ENGINEER, Role.ADMIN])
def test_post_reviews_sufficient_role_not_403(client, auth, role):
    r = client.post("/api/v1/reviews", json=_REVIEW_CREATE_BODY, headers=auth(role))
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# POST /api/v1/reviews/{id}/complete — Reviewer or Admin only (require_exact_role)
# MLEngineer and DataEngineer should get 403.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [Role.VIEWER, Role.ML_ENGINEER, Role.DATA_ENGINEER])
def test_complete_review_wrong_role_gets_403(client, auth, role):
    """Non-Reviewer/non-Admin roles must be rejected with 403."""
    r = client.post(
        f"/api/v1/reviews/{_DUMMY_REVIEW_ID}/complete",
        json=_REVIEW_COMPLETE_BODY,
        headers=auth(role),
    )
    assert r.status_code == 403, f"expected 403 for {role}, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ADMIN])
def test_complete_review_allowed_role_not_403(client, auth, role):
    """Reviewer and Admin must pass the auth check (404 for missing id is fine)."""
    r = client.post(
        f"/api/v1/reviews/{_DUMMY_REVIEW_ID}/complete",
        json=_REVIEW_COMPLETE_BODY,
        headers=auth(role),
    )
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# POST /api/v1/drift/run — DataEngineer+
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [Role.VIEWER, Role.REVIEWER, Role.ML_ENGINEER])
def test_post_drift_run_under_privileged_gets_403(client, auth, role):
    r = client.post("/api/v1/drift/run", json=_DRIFT_BODY, headers=auth(role))
    assert r.status_code == 403, f"expected 403 for {role}, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.DATA_ENGINEER, Role.ADMIN])
def test_post_drift_run_sufficient_role_not_403(client, auth, role):
    r = client.post("/api/v1/drift/run", json=_DRIFT_BODY, headers=auth(role))
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# GET /api/v1/drift/metrics — Viewer+ (everyone should access)
# ---------------------------------------------------------------------------

def test_get_drift_metrics_viewer_not_403(client, auth):
    """Viewer is the minimum role; must not get 403."""
    r = client.get("/api/v1/drift/metrics", headers=auth(Role.VIEWER))
    assert r.status_code != 403, f"expected not-403 for Viewer, got {r.status_code}: {r.text}"
    assert r.status_code == 200, f"expected 200 for Viewer, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ML_ENGINEER, Role.DATA_ENGINEER, Role.ADMIN])
def test_get_drift_metrics_all_roles_not_403(client, auth, role):
    r = client.get("/api/v1/drift/metrics", headers=auth(role))
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# POST /api/v1/datasets/build — MLEngineer+
# ---------------------------------------------------------------------------

def test_post_datasets_build_viewer_gets_403(client, auth):
    r = client.post("/api/v1/datasets/build", json=_DATASET_BODY, headers=auth(Role.VIEWER))
    assert r.status_code == 403, f"expected 403 for Viewer, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.ML_ENGINEER, Role.DATA_ENGINEER, Role.ADMIN])
def test_post_datasets_build_sufficient_role_not_403(client, auth, role):
    r = client.post("/api/v1/datasets/build", json=_DATASET_BODY, headers=auth(role))
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# POST /api/v1/gold/republish — Admin only
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [Role.VIEWER, Role.REVIEWER, Role.ML_ENGINEER, Role.DATA_ENGINEER])
def test_post_gold_republish_non_admin_gets_403(client, auth, role):
    r = client.post("/api/v1/gold/republish", json=_GOLD_BODY, headers=auth(role))
    assert r.status_code == 403, f"expected 403 for {role}, got {r.status_code}: {r.text}"


def test_post_gold_republish_admin_not_403(client, auth):
    r = client.post("/api/v1/gold/republish", json=_GOLD_BODY, headers=auth(Role.ADMIN))
    assert r.status_code != 403, f"expected not-403 for Admin, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# GET /api/v1/audit/lineage — DataEngineer+
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [Role.VIEWER, Role.REVIEWER, Role.ML_ENGINEER])
def test_get_audit_lineage_under_privileged_gets_403(client, auth, role):
    r = client.get("/api/v1/audit/lineage", params={"entity_id": "any"}, headers=auth(role))
    assert r.status_code == 403, f"expected 403 for {role}, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.DATA_ENGINEER, Role.ADMIN])
def test_get_audit_lineage_sufficient_role_not_403(client, auth, role):
    r = client.get("/api/v1/audit/lineage", params={"entity_id": "any"}, headers=auth(role))
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# GET /api/v1/dashboard/metrics — Viewer+
# ---------------------------------------------------------------------------

def test_get_dashboard_metrics_viewer_gets_200(client, auth):
    """Viewer is the minimum role; metrics must return 200."""
    r = client.get("/api/v1/dashboard/metrics", headers=auth(Role.VIEWER))
    assert r.status_code == 200, f"expected 200 for Viewer, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ML_ENGINEER, Role.DATA_ENGINEER, Role.ADMIN])
def test_get_dashboard_metrics_all_roles_not_403(client, auth, role):
    r = client.get("/api/v1/dashboard/metrics", headers=auth(role))
    assert r.status_code != 403, f"expected not-403 for {role}, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# Unknown X-Role header → 401
# ---------------------------------------------------------------------------

def test_unknown_role_header_returns_401(client):
    """An unrecognised role value in X-Role must yield 401."""
    r = client.get(
        "/api/v1/dashboard/metrics",
        headers={"X-Role": "SuperAdmin", "X-User-Id": "tester"},
    )
    assert r.status_code == 401, f"expected 401 for unknown role, got {r.status_code}: {r.text}"
