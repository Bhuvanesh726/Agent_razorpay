from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.database import get_db
from app.schemas.audit import AuditEventOut

router = APIRouter(tags=["audit"])
_audit = AuditService()


@router.get("/api/audit/{session_id}", response_model=list[AuditEventOut])
def get_audit_trail(session_id: str, db: Session = Depends(get_db)) -> list[AuditEventOut]:
    return _audit.get_trail(db, session_id)
