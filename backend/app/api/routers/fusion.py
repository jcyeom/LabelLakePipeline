"""Fusion router (backend_design_prd 절차 4, FR-4, §9.3)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.deps import Identity, require_role
from app.api.jobs import execute_run
from app.db import get_session, get_session_factory
from app.domain.enums import Role
from app.domain.schemas import FusionRunRequest, RunAcceptedResponse
from app.repositories.runs import RunRepository
from app.services.fusion import FusionService

router = APIRouter(prefix="/api/v1/fusion", tags=["fusion"])


@router.post("/run", response_model=RunAcceptedResponse, status_code=202)
def run_fusion(
    req: FusionRunRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    session_factory=Depends(get_session_factory),
    identity: Identity = Depends(require_role(Role.DATA_ENGINEER)),
) -> RunAcceptedResponse:
    """Schedule fusion asynchronously: 202 + run_id; poll GET /api/v1/runs/{run_id}."""
    run = RunRepository(session).start(
        "fusion", params={"policy": req.fusion_policy.value, "sample_ids": req.sample_ids}
    )
    session.commit()  # make the run row visible to the background job's own session
    actor = identity.user_id

    def work(s, run_id: str) -> dict:
        return FusionService(s).run(
            req.sample_ids,
            policy=req.fusion_policy,
            confidence_gap_threshold=req.confidence_gap_threshold,
            disagreement_threshold=req.disagreement_threshold,
            low_confidence_threshold=req.low_confidence_threshold,
            actor=actor,
            run_id=run_id,
        ).model_dump(mode="json")

    background.add_task(execute_run, run.run_id, work, session_factory)
    return RunAcceptedResponse(run_id=run.run_id, poll_url=f"/api/v1/runs/{run.run_id}")
