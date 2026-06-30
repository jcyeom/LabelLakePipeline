"""Tests for L1 storage & retrieval (FR-1/FR-2, AC-1)."""
from __future__ import annotations

from app.domain.enums import Role
from tests.conftest import l1_payload


def test_create_l1_returns_created(client, auth):
    r = client.post("/api/v1/labels/l1", json=l1_payload(), headers=auth(Role.DATA_ENGINEER))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "CREATED"
    assert body["label_id"].startswith("l1-")


def test_missing_inputs_hash_rejected_422(client, auth):
    payload = l1_payload()
    payload.pop("inputs_hash")
    r = client.post("/api/v1/labels/l1", json=payload, headers=auth(Role.DATA_ENGINEER))
    assert r.status_code == 422  # FR-1 수용 기준: inputs_hash 누락 시 저장 실패


def test_missing_method_ver_rejected_422(client, auth):
    payload = l1_payload(method_ver="")
    r = client.post("/api/v1/labels/l1", json=payload, headers=auth(Role.DATA_ENGINEER))
    assert r.status_code == 422  # FR-1 수용 기준: method_ver 누락 시 저장 실패


def test_multiple_labelers_same_sample(client, auth):
    """AC-1: rule + llm labels for the same sample stored as separate objects."""
    h = auth(Role.DATA_ENGINEER)
    client.post("/api/v1/labels/l1", json=l1_payload(method="rule", method_ver="rule-v1", value="medium_risk", confidence=0.7), headers=h)
    client.post("/api/v1/labels/l1", json=l1_payload(method="llm", method_ver="llm-v2", value="high_risk", confidence=0.82), headers=h)

    r = client.get("/api/v1/labels/l1", params={"sample_id": "sample-001"}, headers=auth(Role.ML_ENGINEER))
    assert r.status_code == 200
    labels = r.json()["labels"]
    assert len(labels) == 2
    assert {l["method"] for l in labels} == {"rule", "llm"}


def test_get_l1_empty_list(client, auth):
    r = client.get("/api/v1/labels/l1", params={"sample_id": "nope"}, headers=auth(Role.ML_ENGINEER))
    assert r.status_code == 200
    assert r.json()["labels"] == []


def test_l2_not_found_returns_404(client, auth):
    r = client.get("/api/v1/labels/l2", params={"sample_id": "sample-001"}, headers=auth(Role.ML_ENGINEER))
    assert r.status_code == 404
    assert r.json()["error_code"] == "NOT_FOUND"


def test_rbac_viewer_cannot_create_l1(client, auth):
    r = client.post("/api/v1/labels/l1", json=l1_payload(), headers=auth(Role.VIEWER))
    assert r.status_code == 403
