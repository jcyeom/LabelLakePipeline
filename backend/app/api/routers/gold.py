"""Gold republish router (backend_design_prd 절차 9, FR-8)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.deps import Identity, require_role
from app.api.jobs import execute_run
from app.db import get_session, get_session_factory
from app.domain.enums import Role
from app.domain.schemas import (
    GoldRepublishRequest,
    GoldRollbackResponse,
    RunAcceptedResponse,
)
from app.errors import NotFoundError
from app.repositories.runs import RunRepository
from app.services.gold import GoldRepublishService

router = APIRouter(prefix="/api/v1/gold", tags=["gold"])


@router.post("/republish", response_model=RunAcceptedResponse, status_code=202)
def republish(
    req: GoldRepublishRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    session_factory=Depends(get_session_factory),
    identity: Identity = Depends(require_role(Role.ADMIN)),
) -> RunAcceptedResponse:
    """Schedule Gold republish asynchronously: 202 + run_id; poll /api/v1/runs/{run_id}."""
    run = RunRepository(session).start(
        "republish", params={"trigger": req.trigger, "policy": (req.fusion_policy.value if req.fusion_policy else None)}
    )
    session.commit()
    actor = identity.user_id

    def work(s, run_id: str) -> dict:
        return GoldRepublishService(s).republish(req, actor=actor, run_id=run_id).model_dump(mode="json")

    background.add_task(execute_run, run.run_id, work, session_factory)
    return RunAcceptedResponse(run_id=run.run_id, poll_url=f"/api/v1/runs/{run.run_id}")


@router.post("/rollback/{version_id}", response_model=GoldRollbackResponse)
def rollback(
    version_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_role(Role.ADMIN)),
) -> GoldRollbackResponse:
    """Re-activate a previous Gold version (FR-8 rollback, B-G5)."""
    version = GoldRepublishService(session).rollback(version_id, actor=identity.user_id)
    if version is None:
        raise NotFoundError(f"gold version {version_id} not found")
    return GoldRollbackResponse(
        version_id=version.version_id,
        label_version=version.label_version,
        is_active=bool(version.is_active),
    )
