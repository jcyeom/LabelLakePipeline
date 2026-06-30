"""Async batch job failure path.

Production-critical: when a background job raises, the run must be marked FAILED with
the error recorded (no stuck-RUNNING). TestClient runs the BackgroundTask within the
POST call, so we can poll immediately. Covers app/api/jobs.py failure branch +
RunRepository.fail.
"""
from __future__ import annotations

from app.domain.enums import Role
from app.services.drift import DriftService
from app.services.fusion import FusionService


def test_failed_fusion_job_records_failed_status_and_error(client, auth, monkeypatch):
    def boom(self, *args, **kwargs):
        raise RuntimeError("kaboom in fusion")

    monkeypatch.setattr(FusionService, "run", boom)

    r = client.post("/api/v1/fusion/run", json={"sample_ids": ["x"]}, headers=auth(Role.DATA_ENGINEER))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]

    poll = client.get(f"/api/v1/runs/{run_id}", headers=auth(Role.DATA_ENGINEER))
    assert poll.status_code == 200, poll.text
    body = poll.json()
    assert body["status"] == "FAILED"
    assert "kaboom" in (body["error"] or "")
    assert body["finished_at"] is not None


def test_failed_drift_job_records_failed_status(client, auth, monkeypatch):
    def boom(self, *args, **kwargs):
        raise ValueError("drift exploded")

    monkeypatch.setattr(DriftService, "run", boom)

    r = client.post(
        "/api/v1/drift/run",
        json={
            "method": "llm",
            "method_ver": "v1",
            "baseline_window": "2026-01-01T00:00:00/2026-02-01T00:00:00",
            "current_window": "2026-02-01T00:00:00/2026-03-01T00:00:00",
            "metrics": ["psi"],
        },
        headers=auth(Role.DATA_ENGINEER),
    )
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]

    body = client.get(f"/api/v1/runs/{run_id}", headers=auth(Role.DATA_ENGINEER)).json()
    assert body["status"] == "FAILED"
    assert "drift exploded" in (body["error"] or "")


def test_failed_job_error_is_truncated(client, auth, monkeypatch):
    """A very long exception message is truncated before being stored on the run."""
    long_msg = "E" * 5000

    def boom(self, *args, **kwargs):
        raise RuntimeError(long_msg)

    monkeypatch.setattr(FusionService, "run", boom)

    r = client.post("/api/v1/fusion/run", json={"sample_ids": ["x"]}, headers=auth(Role.DATA_ENGINEER))
    run_id = r.json()["run_id"]
    body = client.get(f"/api/v1/runs/{run_id}", headers=auth(Role.DATA_ENGINEER)).json()
    assert body["status"] == "FAILED"
    assert len(body["error"]) <= 2000
