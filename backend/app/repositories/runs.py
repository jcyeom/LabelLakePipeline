"""Run registry repository (backend_design_prd 절차 13, FR-10)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.orm import LabelerRun
from app.util import new_id, now_utc


class RunRepository:
    def __init__(self, session: Session):
        self.session = session

    def start(self, run_type: str, *, method=None, method_ver=None, params=None, run_id=None) -> LabelerRun:
        row = LabelerRun(
            run_id=run_id or new_id("run"),
            run_type=run_type,
            method=method,
            method_ver=method_ver,
            status="RUNNING",
            params=params,
            started_at=now_utc(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def finish(self, run_id: str, *, created_count=0, failed_count=0, status="COMPLETED") -> Optional[LabelerRun]:
        row = self.session.get(LabelerRun, run_id)
        if row is None:
            return None
        row.created_count = created_count
        row.failed_count = failed_count
        row.status = status
        row.finished_at = now_utc()
        self.session.flush()
        return row

    def set_result(self, run_id: str, result, *, status: str = "COMPLETED") -> Optional[LabelerRun]:
        """Store an async job's full result and mark it finished (run polling)."""
        row = self.session.get(LabelerRun, run_id)
        if row is None:
            return None
        row.result = result
        row.status = status
        if row.finished_at is None:
            row.finished_at = now_utc()
        self.session.flush()
        return row

    def fail(self, run_id: str, error: str) -> Optional[LabelerRun]:
        row = self.session.get(LabelerRun, run_id)
        if row is None:
            return None
        row.status = "FAILED"
        row.error = error
        row.finished_at = now_utc()
        self.session.flush()
        return row

    def get(self, run_id: str) -> Optional[LabelerRun]:
        return self.session.get(LabelerRun, run_id)
