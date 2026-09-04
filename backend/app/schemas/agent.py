from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str
    message: str
    budget_paise: int | None = None


class AgentChatRequest(BaseModel):
    """Interactive chat scoped to a specific AgentCredential — no budget
    field: the credential's own spend_limit_paise is the only cap. See
    POST /api/agents/{credential_id}/chat."""

    session_id: str
    message: str


class QuickBuyRequest(BaseModel):
    session_id: str
    sku: str
    quantity: int = 1


class ConfirmRequest(BaseModel):
    session_id: str
    approve: bool = True


class PendingActionOut(BaseModel):
    tool_name: str | None = None
    arguments: dict | None = None
    rule_name: str | None = None
    reason: str | None = None


class PaymentInfoOut(BaseModel):
    order_id: int
    razorpay_order_id: str
    amount_paise: int
    currency: str
    razorpay_key_id: str
    status: str


class UpsellOfferOut(BaseModel):
    sku: str
    name: str
    price_paise: int
    reason: str


class ProductSuggestionOut(BaseModel):
    sku: str
    name: str
    unit: str
    price_paise: int
    price_display: str
    stock: int
    within_budget: bool
    note: str


class ChatResponse(BaseModel):
    reply: str
    status: str  # "completed" | "awaiting_confirmation" | "iteration_limit"
    pending: PendingActionOut | None = None
    cart: dict
    payment: PaymentInfoOut | None = None
    upsell: UpsellOfferOut | None = None
    product_suggestion: ProductSuggestionOut | None = None
