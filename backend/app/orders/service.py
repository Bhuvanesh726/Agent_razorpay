"""Order orchestration: idempotent order creation, Razorpay order creation
(also idempotent — reuses an existing razorpay_order_id rather than ever
creating a second one for the same row), and the PAID/FAILED transitions.

Deliberately has no knowledge of the agent, the policy engine, or HTTP —
those layers call into this one, not the other way around.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.cart import Cart
from app.models.order import Order, Payment
from app.orders import repository as order_repo
from app.orders.idempotency import compute_idempotency_key
from app.orders.state_machine import OrderStatus, require_transition
from app.payments.gateway import PaymentGatewayError, gateway
from app.repositories import cart_repo


class EmptyCartError(Exception):
    pass


@dataclass
class OrderCreationResult:
    order: Order
    was_duplicate: bool  # True if an order for this idempotency key already existed


def _line_items(cart: Cart) -> list[tuple[str, int, int]]:
    return [(item.product.sku, item.quantity, item.unit_price_paise) for item in cart.items]


def create_or_get_order(db: Session, *, user_id: str, session_id: str, cart: Cart) -> OrderCreationResult:
    if not cart.items:
        raise EmptyCartError("Cart is empty — nothing to pay for.")

    line_items = _line_items(cart)
    amount_paise = sum(qty * price for _, qty, price in line_items)
    key = compute_idempotency_key(user_id, line_items, amount_paise)

    order, created = order_repo.get_or_create(
        db,
        idempotency_key=key,
        user_id=user_id,
        session_id=session_id,
        cart_id=cart.id,
        amount_paise=amount_paise,
        currency=settings.razorpay_currency,
    )
    return OrderCreationResult(order=order, was_duplicate=not created)


def ensure_razorpay_order(db: Session, order: Order) -> Order:
    """Idempotent at the Razorpay level too: if this order already has a
    razorpay_order_id, reuse it rather than creating a second Razorpay order
    for the same row (this is what makes rapid double-clicks on Confirm safe,
    not just the DB-level uniqueness)."""
    if order.razorpay_order_id:
        # A retry after a prior failed attempt (declined card, bad signature)
        # reuses the same Razorpay order rather than creating a new one — but
        # the status still needs to move off FAILED, or it would misreport a
        # payment attempt that's actually back in progress.
        if OrderStatus(order.status) == OrderStatus.FAILED:
            require_transition(OrderStatus.FAILED, OrderStatus.AWAITING_CONFIRMATION)
            order.status = OrderStatus.AWAITING_CONFIRMATION.value
            order_repo.save(db, order)
        return order

    require_transition(OrderStatus(order.status), OrderStatus.AWAITING_CONFIRMATION)

    try:
        rp_order = gateway.create_order(order.amount_paise, order.currency, receipt=f"order-{order.id}")
    except PaymentGatewayError:
        order.status = OrderStatus.FAILED.value
        order_repo.save(db, order)
        raise

    order.razorpay_order_id = rp_order.razorpay_order_id
    order.status = OrderStatus.AWAITING_CONFIRMATION.value
    return order_repo.save(db, order)


def mark_paid(
    db: Session, order: Order, *, razorpay_payment_id: str, method: str | None, raw_response: dict | None
) -> Payment:
    require_transition(OrderStatus(order.status), OrderStatus.PAID)
    order.status = OrderStatus.PAID.value
    order_repo.save(db, order)

    payment = Payment(
        order_id=order.id,
        razorpay_payment_id=razorpay_payment_id,
        status="captured",
        amount_paise=order.amount_paise,
        method=method,
        raw_response=raw_response,
    )
    order_repo.add_payment(db, payment)

    _reset_cart_after_payment(db, order)
    return payment


def mark_failed(
    db: Session,
    order: Order,
    *,
    error_code: str | None,
    error_description: str | None,
    razorpay_payment_id: str | None = None,
    raw_response: dict | None = None,
) -> Payment:
    current = OrderStatus(order.status)
    if current != OrderStatus.PAID:  # never downgrade a paid order on a stale/duplicate failure report
        require_transition(current, OrderStatus.FAILED)
        order.status = OrderStatus.FAILED.value
        order_repo.save(db, order)

    payment = Payment(
        order_id=order.id,
        razorpay_payment_id=razorpay_payment_id,
        status="failed",
        amount_paise=order.amount_paise,
        error_code=error_code,
        error_description=error_description,
        raw_response=raw_response,
    )
    return order_repo.add_payment(db, payment)


def _reset_cart_after_payment(db: Session, order: Order) -> None:
    cart = cart_repo.get_by_id(db, order.cart_id)
    if cart is not None and cart.status == "active":
        cart_repo.mark_checked_out(db, cart)
    cart_repo.get_or_create_active_cart(db, order.user_id)
