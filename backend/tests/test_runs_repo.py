"""RunRepository unit tests — run lifecycle (start/finish/set_result/fail) and the
missing-row guards used by the async job runner."""
from __future__ import annotations

from app.repositories.runs import RunRepository


def test_fail_sets_failed_status_and_error(db_session):
    repo = RunRepository(db_session)
    run = repo.start("fusion", params={"k": "v"})
    out = repo.fail(run.run_id, "boom")
    assert out is not None
    assert out.status == "FAILED"
    assert out.error == "boom"
    assert out.finished_at is not None


def test_finish_sets_counts_and_completed(db_session):
    repo = RunRepository(db_session)
    run = repo.start("drift")
    out = repo.finish(run.run_id, created_count=3, failed_count=1)
    assert out.status == "COMPLETED"
    assert out.created_count == 3
    assert out.failed_count == 1
    assert out.finished_at is not None


def test_set_result_stores_result_and_completes(db_session):
    repo = RunRepository(db_session)
    run = repo.start("fusion")
    out = repo.set_result(run.run_id, {"created_l2_count": 2})
    assert out.status == "COMPLETED"
    assert out.result == {"created_l2_count": 2}


def test_set_result_preserves_existing_finished_at(db_session):
    repo = RunRepository(db_session)
    run = repo.start("republish")
    finished = repo.finish(run.run_id, created_count=1)
    first_ts = finished.finished_at
    repo.set_result(run.run_id, {"version_id": "v1"})
    again = repo.get(run.run_id)
    assert again.finished_at == first_ts  # not overwritten by set_result
    assert again.result == {"version_id": "v1"}


def test_finish_missing_run_returns_none(db_session):
    assert RunRepository(db_session).finish("run-missing") is None


def test_set_result_missing_run_returns_none(db_session):
    assert RunRepository(db_session).set_result("run-missing", {"x": 1}) is None


def test_fail_missing_run_returns_none(db_session):
    assert RunRepository(db_session).fail("run-missing", "err") is None


def test_start_with_explicit_run_id_is_reused(db_session):
    repo = RunRepository(db_session)
    run = repo.start("fusion", run_id="run-fixed")
    assert run.run_id == "run-fixed"
    assert repo.get("run-fixed") is not None
