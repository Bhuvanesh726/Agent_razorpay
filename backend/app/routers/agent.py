from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.agent import harness
from app.core.config import settings
from app.database import get_db
from app.schemas.agent import ChatRequest, ChatResponse, ConfirmRequest, PendingActionOut

router = APIRouter(tags=["agent"])

# No auth yet (later layer). Every request acts on the single demo user.
CURRENT_USER_ID = settings.default_user_id


def _to_response(result) -> ChatResponse:
    return ChatResponse(
        reply=result.reply,
        status=result.status,
        pending=PendingActionOut(**result.pending) if result.pending else None,
        cart=result.cart,
    )


@router.post("/api/agent/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request, db: Session = Depends(get_db)) -> ChatResponse:
    request_id = getattr(request.state, "request_id", None)
    result = harness.handle_chat(
        db, payload.session_id, CURRENT_USER_ID, payload.message, payload.budget_paise, request_id
    )
    return _to_response(result)


@router.post("/api/agent/confirm", response_model=ChatResponse)
def confirm(payload: ConfirmRequest, request: Request, db: Session = Depends(get_db)) -> ChatResponse:
    request_id = getattr(request.state, "request_id", None)
    result = harness.handle_confirm(db, payload.session_id, CURRENT_USER_ID, payload.approve, request_id)
    return _to_response(result)
