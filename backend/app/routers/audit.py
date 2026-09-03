from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.replay import replay_session
from app.audit.service import AuditService
from app.auth.deps import get_principal
from app.auth.principal import Principal
from app.auth.routing import AuthRequirement, SecureAPIRoute, requires
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.user import User
from app.repositories import agent_session_repo
from app.schemas.audit import AuditSessionSummaryOut, AuditTotalsOut, AuditTrailOut, SessionReplayOut

router = APIRouter(tags=["audit"], route_class=SecureAPIRoute)
_audit = AuditService()


# Registered ahead of GET /api/audit/{session_id} below: Starlette matches
# routes in registration order, and a literal "/api/audit/sessions" would
# otherwise be swallowed by the {session_id} path param (session_id="sessions").
@router.get("/api/audit/sessions", response_model=list[AuditSessionSummaryOut])
@requires(AuthRequirement.MERCHANT)
def list_recent_audit_sessions(
    limit: int = 20, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[AuditSessionSummaryOut]:
    """A merchant-only picker feeding the audit viewer: the alternative was
    requiring a merchant to get a session_id handed to them by a buyer (or
    dug out of the shopping assistant's own "Show audit trail" link) before
    they could look anything up at all."""
    sessions = agent_session_repo.list_recent_sessions(db, limit=limit)
    if not sessions:
        return []
    session_ids = [s.session_id for s in sessions]
    user_ids = {s.user_id for s in sessions}
    emails = dict(db.execute(select(User.id, User.email).where(User.id.in_(user_ids))).all())
    counts = dict(
        db.execute(
            select(AuditEvent.session_id, func.count(AuditEvent.id))
            .where(AuditEvent.session_id.in_(session_ids))
            .group_by(AuditEvent.session_id)
        ).all()
    )
    return [
        AuditSessionSummaryOut(
            session_id=s.session_id,
            user_email=emails.get(s.user_id, s.user_id),
            status=s.status,
            created_at=s.created_at,
            updated_at=s.updated_at,
            event_count=counts.get(s.session_id, 0),
        )
        for s in sessions
    ]


def _check_session_access(db: Session, session_id: str, principal: Principal) -> None:
    """Merchants can read any session's trail (campaign runs have no
    AgentSession row at all, and reviewing any buyer's trail is part of the
    merchant role). Buyers and agents are both scoped to sessions owned by
    that buyer — an agent's Principal.user_id is its credential's owner, so
    an agent can see its own runs but not another buyer's. A session_id that
    doesn't exist, or belongs to someone else, is reported identically as
    404 so this endpoint can't be used to probe which session ids are
    real."""
    if principal.type == "merchant":
        return
    session = agent_session_repo.get_session(db, session_id)
    if session is None or session.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail=f"No session '{session_id}'.")


@router.get("/api/audit/{session_id}", response_model=AuditTrailOut)
@requires(AuthRequirement.BUYER, AuthRequirement.MERCHANT, AuthRequirement.AGENT)
def get_audit_trail(
    session_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> AuditTrailOut:
    _check_session_access(db, session_id, principal)
    events = _audit.get_trail(db, session_id)
    totals = _audit.compute_totals(events)
    return AuditTrailOut(session_id=session_id, events=events, totals=AuditTotalsOut(**totals))


@router.get("/api/audit/{session_id}/replay", response_model=SessionReplayOut)
@requires(AuthRequirement.BUYER, AuthRequirement.MERCHANT, AuthRequirement.AGENT)
def get_session_replay(
    session_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> SessionReplayOut:
    """Reconstructs the session from audit_events alone — proof the log is
    self-sufficient, not just a display convenience."""
    _check_session_access(db, session_id, principal)
    replay = replay_session(db, session_id)
    return SessionReplayOut(
        session_id=replay.session_id,
        event_count=len(replay.events),
        narrative=replay.narrative,
        final_cart=replay.final_cart,
        final_order_status=replay.final_order_status,
    )
