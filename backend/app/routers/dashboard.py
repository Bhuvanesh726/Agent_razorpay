"""The buyer dashboard — Layer 4.8. One page's worth of data: their most
recent agent (or a prompt to create one), recent orders, and the current
cart. Full agent management is reused as-is from Layer 4.7's /agents UI —
this endpoint only summarizes.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_principal
from app.auth.principal import Principal
from app.auth.routing import AuthRequirement, SecureAPIRoute, requires
from app.database import get_db
from app.models.agent_credential import AgentCredential
from app.orders import repository as order_repo
from app.schemas.dashboard import AgentSummaryLite, DashboardSummaryOut, OrderSummaryOut
from app.services import cart_service

router = APIRouter(tags=["dashboard"], route_class=SecureAPIRoute)


@router.get("/api/dashboard/summary", response_model=DashboardSummaryOut)
@requires(AuthRequirement.BUYER)
def get_summary(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> DashboardSummaryOut:
    agents = list(
        db.scalars(
            select(AgentCredential)
            .where(AgentCredential.owner_user_id == principal.user_id)
            .order_by(AgentCredential.created_at.desc())
        )
    )
    latest = agents[0] if agents else None

    orders = order_repo.list_by_user(db, principal.user_id, limit=5)
    cart = cart_service.get_cart(db, principal.user_id)

    return DashboardSummaryOut(
        agent=AgentSummaryLite(id=latest.id, name=latest.name, status=latest.status, delivery_mode=latest.delivery_mode)
        if latest
        else None,
        agent_count=len(agents),
        recent_orders=[
            OrderSummaryOut(id=o.id, amount_paise=o.amount_paise, status=o.status, created_at=o.created_at)
            for o in orders
        ],
        cart=cart,
    )
