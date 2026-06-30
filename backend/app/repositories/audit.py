"""Audit / lineage repository (backend_design_prd 절차 10, FR-10)."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.orm import AuditLog
from app.util import new_id, now_utc

ALERT_ENTITY = "alert"


class AuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def record_alert(self, *, severity: str, source: str, message: str, details=None) -> AuditLog:
        """Emit an alert event (FR-7/§13.2). Stored in audit_log under the 'alert' entity."""
        return self.record(
            entity_type=ALERT_ENTITY,
            entity_id=new_id("alert"),
            action=severity,
            details={"severity": severity, "source": source, "message": message, "extra": details},
        )

    def list_alerts(self, *, limit: int = 100) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.entity_type == ALERT_ENTITY)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def record(self, *, entity_type, entity_id, action, actor=None, run_id=None, details=None) -> AuditLog:
        row = AuditLog(
            audit_id=new_id("audit"),
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            run_id=run_id,
            details=details,
            created_at=now_utc(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def by_entity(self, entity_type: str, entity_id: str) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at)
        )
        return list(self.session.scalars(stmt))

    def by_id_or_run(self, entity_id: str, *, limit: int = 100, offset: int = 0) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(or_(AuditLog.entity_id == entity_id, AuditLog.run_id == entity_id))
            .order_by(AuditLog.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt))
