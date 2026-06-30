"""Drift routers (backend_design_prd 절차 8, FR-7, §9.6)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Identity, require_role
from app.api.jobs import execute_run
from app.api.pagination import PageParams, page_params
from app.db import get_session, get_session_factory
from app.domain.enums import Role
from app.domain.schemas import DriftMetricView, DriftRunRequest, RunAcceptedResponse
from app.repositories.drift import DriftRepository
from app.repositories.runs import RunRepository
from app.services.drift import DriftService

router = APIRouter(prefix="/api/v1/drift", tags=["drift"])


@router.post("/run", response_model=RunAcceptedResponse, status_code=202)
def run_drift(
    req: DriftRunRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    session_factory=Depends(get_session_factory),
    identity: Identity = Depends(require_role(Role.DATA_ENGINEER)),
) -> RunAcceptedResponse:
    """Schedule drift measurement asynchronously: 202 + run_id; poll /api/v1/runs/{run_id}."""
    run = RunRepository(session).start("drift", method=req.method.value, method_ver=req.method_ver)
    session.commit()
    actor = identity.user_id

    def work(s, run_id: str) -> dict:
        return DriftService(s).run(req, actor=actor, run_id=run_id).model_dump(mode="json")

    background.add_task(execute_run, run.run_id, work, session_factory)
    return RunAcceptedResponse(run_id=run.run_id, poll_url=f"/api/v1/runs/{run.run_id}")


@router.get("/metrics", response_model=list[DriftMetricView])
def list_metrics(
    method: Optional[str] = Query(default=None),
    page: PageParams = Depends(page_params),
    session: Session = Depends(get_session),
    _identity: Identity = Depends(require_role(Role.VIEWER)),
) -> list[DriftMetricView]:
    rows = DriftRepository(session).list(method=method, limit=page.limit, offset=page.offset)
    return [DriftMetricView.model_validate(r) for r in rows]
