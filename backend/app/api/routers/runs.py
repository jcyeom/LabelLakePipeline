"""Run registry router — poll the status/result of async batch jobs (FR-10).

fusion/drift/gold-republish run endpoints register a LabelerRun and execute in the
background; clients poll GET /api/v1/runs/{run_id} for status and result counts.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import Identity, require_role
from app.db import get_session
from app.domain.enums import Role, role_at_least
from app.domain.schemas import RunView
from app.errors import NotFoundError
from app.repositories.runs import RunRepository

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

# A run's result/params can reveal privileged operation detail (e.g. republish scope),
# so polling requires at least the role that could have submitted that run type.
_RUN_TYPE_MIN_ROLE = {
    "republish": Role.ADMIN,
    "fusion": Role.DATA_ENGINEER,
    "drift": Role.DATA_ENGINEER,
    "dataset": Role.ML_ENGINEER,
}


@router.get("/{run_id}", response_model=RunView)
def get_run(
    run_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_role(Role.VIEWER)),
) -> RunView:
    row = RunRepository(session).get(run_id)
    if row is None:
        raise NotFoundError(f"run {run_id} not found")
    # Deny-by-default: an unmapped (e.g. future privileged) run type requires at least
    # DataEngineer rather than falling open to Viewer.
    required = _RUN_TYPE_MIN_ROLE.get(row.run_type, Role.DATA_ENGINEER)
    if not role_at_least(identity.role, required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"role {identity.role.value} cannot poll a {row.run_type} run",
        )
    return RunView.model_validate(row)
