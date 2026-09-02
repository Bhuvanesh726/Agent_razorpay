"""Append-only by construction: this module defines exactly two operations,
`create` and `list_for_session`. There is no update or delete here, and nowhere
else in the codebase touches the `audit_events` table — so there is no code
path that can mutate a row after it's written.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent


class AuditRepository:
    def create(self, db: Session, event: AuditEvent) -> AuditEvent:
        db.add(event)
        db.flush()
        return event

    def list_for_session(self, db: Session, session_id: str) -> list[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.session_id == session_id)
            .order_by(AuditEvent.id)
        )
        return list(db.scalars(stmt))
