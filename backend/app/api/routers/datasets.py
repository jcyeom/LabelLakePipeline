"""Dataset router (backend_design_prd 절차 7, FR-9, §9.7)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import Identity, require_role
from app.db import get_session
from app.domain.enums import Role
from app.domain.schemas import DatasetBuildRequest, DatasetBuildResponse
from app.services.dataset import DatasetBuilder

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


@router.post("/build", response_model=DatasetBuildResponse, status_code=201)
def build_dataset(
    req: DatasetBuildRequest,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_role(Role.ML_ENGINEER)),
) -> DatasetBuildResponse:
    return DatasetBuilder(session).build(req, actor=identity.user_id)
