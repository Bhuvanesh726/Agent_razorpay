"""The manual "Buy Now" checkout path — a human buyer paying directly,
without going through the chat assistant.

`initiate_payment` (app/agent/tools.py) is already a plain function with no
dependency on the LLM harness or the policy engine, so this endpoint calls
it exactly as the chat tool dispatch does. This mirrors app/routers/cart.py's
own precedent: a buyer's direct REST actions on their own cart/money don't
go through the agent policy engine — that engine exists to bound *agents*
acting on a buyer's behalf, not the buyer spending their own money directly.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.tools import initiate_payment
from app.auth.deps import get_principal
from app.auth.principal import Principal
from app.auth.routing import AuthRequirement, SecureAPIRoute, requires
from app.database import get_db
from app.schemas.agent import PaymentInfoOut
from app.schemas.checkout import CheckoutInitiateRequest

router = APIRouter(tags=["checkout"], route_class=SecureAPIRoute)


@router.post("/api/checkout/initiate", response_model=PaymentInfoOut)
@requires(AuthRequirement.BUYER)
def initiate_checkout(
    payload: CheckoutInitiateRequest,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> PaymentInfoOut:
    result = initiate_payment(db, principal.user_id, payload.session_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return PaymentInfoOut(**result)
