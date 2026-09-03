from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.agent import harness
from app.agent.harness import SessionOwnershipError
from app.auth.deps import get_principal
from app.auth.principal import Principal
from app.auth.routing import AuthRequirement, SecureAPIRoute, requires
from app.database import get_db
from app.schemas.agent import ChatRequest, ChatResponse, ConfirmRequest, PaymentInfoOut, PendingActionOut, UpsellOfferOut

router = APIRouter(tags=["agent"], route_class=SecureAPIRoute)


def _to_response(result) -> ChatResponse:
    return ChatResponse(
        reply=result.reply,
        status=result.status,
        pending=PendingActionOut(**result.pending) if result.pending else None,
        cart=result.cart,
        payment=PaymentInfoOut(**result.payment) if result.payment else None,
        upsell=UpsellOfferOut(**result.upsell) if result.upsell else None,
    )


@router.post("/api/agent/chat", response_model=ChatResponse)
@requires(AuthRequirement.BUYER, AuthRequirement.AGENT)
def chat(
    payload: ChatRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ChatResponse:
    request_id = getattr(request.state, "request_id", None)
    try:
        result = harness.handle_chat(
            db, payload.session_id, principal.user_id, payload.message, payload.budget_paise, request_id
        )
    except SessionOwnershipError:
        raise HTTPException(status_code=403, detail="This session belongs to a different principal.")
    return _to_response(result)


@router.post("/api/agent/confirm", response_model=ChatResponse)
@requires(AuthRequirement.BUYER, AuthRequirement.AGENT)
def confirm(
    payload: ConfirmRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ChatResponse:
    request_id = getattr(request.state, "request_id", None)
    try:
        result = harness.handle_confirm(db, payload.session_id, principal.user_id, payload.approve, request_id)
    except SessionOwnershipError:
        raise HTTPException(status_code=403, detail="This session belongs to a different principal.")
    return _to_response(result)
