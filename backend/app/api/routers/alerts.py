"""Alerts router (FR-7/§13.2 알림 이벤트). Lists alert events recorded by services."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Identity, require_role
from app.db import get_session
from app.domain.enums import Role
from app.domain.schemas import AlertListResponse, AlertView
from app.repositories.audit import AuditRepository

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", response_model=AlertListResponse)
def list_alerts(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    _identity: Identity = Depends(require_role(Role.VIEWER)),
) -> AlertListResponse:
    rows = AuditRepository(session).list_alerts(limit=limit)
    alerts = []
    for r in rows:
        d = r.details or {}
        alerts.append(
            AlertView(
                alert_id=r.audit_id,
                severity=d.get("severity", r.action),
                source=d.get("source", "unknown"),
                message=d.get("message", ""),
                details=d.get("extra"),
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
        )
    return AlertListResponse(count=len(alerts), alerts=alerts)
