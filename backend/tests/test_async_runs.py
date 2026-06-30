"""Async batch endpoints (P1): fusion/drift/republish return 202 + run_id and are
polled via GET /api/v1/runs/{run_id}, which carries the job result."""
from __future__ import annotations

from app.domain.enums import Role
from tests.conftest import l1_payload, submit_and_wait


def _seed_agreeing(client, auth, sample_id):
    for m, mv in (("rule", "rule-v1"), ("llm", "llm-v1")):
        client.post(
            "/api/v1/labels/l1",
            json=l1_payload(sample_id=sample_id, method=m, method_ver=mv, value="high_risk", confidence=0.9),
            headers=auth(Role.DATA_ENGINEER),
        )


def test_fusion_run_returns_202_with_poll_handle(client, auth):
    _seed_agreeing(client, auth, "async-a")
    r = client.post(
        "/api/v1/fusion/run",
        json={"sample_ids": ["async-a"]},
        headers=auth(Role.DATA_ENGINEER),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["run_id"].startswith("run-")
    assert body["status"] == "accepted"
    assert body["poll_url"] == f"/api/v1/runs/{body['run_id']}"


def test_fusion_run_result_available_via_polling(client, auth):
    _seed_agreeing(client, auth, "async-b")
    run = submit_and_wait(client, auth(Role.DATA_ENGINEER), "/api/v1/fusion/run", {"sample_ids": ["async-b"]})
    assert run["run_type"] == "fusion"
    assert run["status"] == "COMPLETED"
    assert run["result"]["created_l2_count"] == 1
    assert run["finished_at"] is not None


def test_drift_run_result_available_via_polling(client, auth):
    run = submit_and_wait(
        client, auth(Role.DATA_ENGINEER), "/api/v1/drift/run",
        {
            "method": "llm",
            "method_ver": "llm-v1",
            "baseline_window": "2026-01-01T00:00:00/2026-02-01T00:00:00",
            "current_window": "2026-02-01T00:00:00/2026-03-01T00:00:00",
            "metrics": ["psi", "kl_divergence"],
        },
    )
    assert run["run_type"] == "drift"
    assert run["status"] == "COMPLETED"
    assert "status" in run["result"]  # DriftRunResponse carries a drift status


def test_fusion_run_rbac_viewer_forbidden_before_scheduling(client, auth):
    # RBAC is enforced synchronously, before any background work is scheduled.
    r = client.post("/api/v1/fusion/run", json={"sample_ids": ["x"]}, headers=auth(Role.VIEWER))
    assert r.status_code == 403


def test_poll_unknown_run_returns_404(client, auth):
    r = client.get("/api/v1/runs/run-nope", headers=auth(Role.VIEWER))
    assert r.status_code == 404
    assert r.json()["error_code"] == "NOT_FOUND"


def test_republish_run_poll_requires_submitter_role(client, auth):
    """A republish run carries privileged scope; only Admin may poll it (security gate)."""
    submitted = client.post("/api/v1/gold/republish", json={"trigger": "t"}, headers=auth(Role.ADMIN))
    assert submitted.status_code == 202, submitted.text
    run_id = submitted.json()["run_id"]

    # DataEngineer is below the republish (Admin) gate.
    denied = client.get(f"/api/v1/runs/{run_id}", headers=auth(Role.DATA_ENGINEER))
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "FORBIDDEN"

    allowed = client.get(f"/api/v1/runs/{run_id}", headers=auth(Role.ADMIN))
    assert allowed.status_code == 200
    assert allowed.json()["run_type"] == "republish"
