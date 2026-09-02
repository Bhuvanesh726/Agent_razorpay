from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.audit.replay import replay_session
from app.audit.service import AuditService
from app.database import get_db
from app.schemas.audit import AuditTotalsOut, AuditTrailOut, SessionReplayOut

router = APIRouter(tags=["audit"])
_audit = AuditService()


@router.get("/api/audit/{session_id}", response_model=AuditTrailOut)
def get_audit_trail(session_id: str, db: Session = Depends(get_db)) -> AuditTrailOut:
    events = _audit.get_trail(db, session_id)
    totals = _audit.compute_totals(events)
    return AuditTrailOut(session_id=session_id, events=events, totals=AuditTotalsOut(**totals))


@router.get("/api/audit/{session_id}/replay", response_model=SessionReplayOut)
def get_session_replay(session_id: str, db: Session = Depends(get_db)) -> SessionReplayOut:
    """Reconstructs the session from audit_events alone — proof the log is
    self-sufficient, not just a display convenience."""
    replay = replay_session(db, session_id)
    return SessionReplayOut(
        session_id=replay.session_id,
        event_count=len(replay.events),
        narrative=replay.narrative,
        final_cart=replay.final_cart,
        final_order_status=replay.final_order_status,
    )
