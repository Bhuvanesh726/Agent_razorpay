from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.database import get_db
from app.schemas.audit import AuditTotalsOut, AuditTrailOut

router = APIRouter(tags=["audit"])
_audit = AuditService()


@router.get("/api/audit/{session_id}", response_model=AuditTrailOut)
def get_audit_trail(session_id: str, db: Session = Depends(get_db)) -> AuditTrailOut:
    events = _audit.get_trail(db, session_id)
    totals = _audit.compute_totals(events)
    return AuditTrailOut(session_id=session_id, events=events, totals=AuditTotalsOut(**totals))
