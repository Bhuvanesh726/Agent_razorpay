from datetime import datetime

from pydantic import BaseModel


class OrderItemOut(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_price_paise: int
    line_total_paise: int


class OrderListItemOut(BaseModel):
    id: int
    status: str
    amount_paise: int
    created_at: datetime
    item_count: int
    # Populated only on the merchant-wide listing — a buyer's own list
    # already knows whose orders they're looking at.
    buyer_email: str | None = None


class OrderDetailOut(BaseModel):
    id: int
    status: str
    amount_paise: int
    currency: str
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut]
    razorpay_payment_id: str | None = None
    # Populated only when the order's latest payment attempt failed — the
    # real code/description Razorpay (or signature verification) reported,
    # not a made-up category. See app/orders/service.py::mark_failed.
    failure_code: str | None = None
    failure_description: str | None = None
    buyer_email: str
