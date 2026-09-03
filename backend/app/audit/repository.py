"""Append-only by construction: every operation here is a create or a read.
There is no update or delete, and nowhere else in the codebase touches the
`audit_events` table — so there is no code path that can mutate a row after
it's written.
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

    def list_by_event_type(self, db: Session, event_type: str) -> list[AuditEvent]:
        """Cross-session, unlike list_for_session — used for merchant-wide
        aggregation (content-gap reporting) where the point is precisely
        that gaps get noticed across every shopper's session, not one."""
        stmt = select(AuditEvent).where(AuditEvent.event_type == event_type).order_by(AuditEvent.id)
        return list(db.scalars(stmt))
