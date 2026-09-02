from sqlalchemy.orm import Session

from app.audit.repository import AuditRepository
from app.models.audit_event import AuditEvent

_repo = AuditRepository()


class AuditService:
    """Every write commits immediately, independent of whatever the caller
    does next — an audit row must survive even if the rest of the request
    later fails or rolls back."""

    def log_event(
        self,
        db: Session,
        *,
        session_id: str,
        user_id: str,
        event_type: str,
        actor: str,
        tool_name: str | None = None,
        tool_args: dict | None = None,
        decision: str | None = None,
        rule_name: str | None = None,
        reason: str | None = None,
        model_used: str | None = None,
        latency_ms: int | None = None,
        request_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            actor=actor,
            tool_name=tool_name,
            tool_args=tool_args,
            decision=decision,
            rule_name=rule_name,
            reason=reason,
            model_used=model_used,
            latency_ms=latency_ms,
            request_id=request_id,
        )
        _repo.create(db, event)
        db.commit()
        db.refresh(event)
        return event

    def get_trail(self, db: Session, session_id: str) -> list[AuditEvent]:
        return _repo.list_for_session(db, session_id)
