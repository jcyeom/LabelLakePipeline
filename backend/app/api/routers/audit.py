"""Audit / lineage router (backend_design_prd 절차 10, FR-10)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Identity, require_role
from app.api.pagination import PageParams, page_params
from app.db import get_session
from app.domain.enums import Role
from app.domain.schemas import LineageResponse
from app.repositories.audit import AuditRepository

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("/lineage", response_model=LineageResponse)
def lineage(
    entity_id: str = Query(..., description="label_id / dataset_id / run_id 등"),
    entity_type: str = Query(default="any"),
    page: PageParams = Depends(page_params),
    session: Session = Depends(get_session),
    _identity: Identity = Depends(require_role(Role.DATA_ENGINEER)),
) -> LineageResponse:
    repo = AuditRepository(session)
    rows = repo.by_id_or_run(entity_id, limit=page.limit, offset=page.offset)
    records = [
        {
            "audit_id": r.audit_id,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "action": r.action,
            "actor": r.actor,
            "run_id": r.run_id,
            "details": r.details,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return LineageResponse(entity_type=entity_type, entity_id=entity_id, records=records)
