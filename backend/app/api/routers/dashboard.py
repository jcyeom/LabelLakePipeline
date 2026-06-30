"""Dashboard router (backend_design_prd 절차 11, §11.1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import Identity, require_role
from app.db import get_session
from app.domain.enums import Role
from app.domain.schemas import DashboardMetrics
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/metrics", response_model=DashboardMetrics)
def dashboard_metrics(
    session: Session = Depends(get_session),
    _identity: Identity = Depends(require_role(Role.VIEWER)),
) -> DashboardMetrics:
    return DashboardService(session).metrics()
