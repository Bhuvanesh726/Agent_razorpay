from datetime import datetime

from pydantic import BaseModel

from app.schemas.cart import CartOut


class AgentSummaryLite(BaseModel):
    id: str
    name: str
    status: str
    delivery_mode: str


class OrderSummaryOut(BaseModel):
    id: int
    amount_paise: int
    status: str
    created_at: datetime


class DashboardSummaryOut(BaseModel):
    # The most recently created agent credential, if any — a prompt to
    # create one is what the buyer dashboard shows instead when this is
    # null. Full management (create/revoke/run/activity) stays on /agents,
    # reused as-is from Layer 4.7 — see docs/048-demand-loop.md.
    agent: AgentSummaryLite | None
    agent_count: int
    recent_orders: list[OrderSummaryOut]
    cart: CartOut
