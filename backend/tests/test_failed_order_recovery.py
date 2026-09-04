"""Reconciliation between our local order status and Razorpay's record.

Two defects, both found on live orders and written up in Failures.md:

1. A verified signature arriving after a failure callback could not move the
   order to PAID, because FAILED → PAID was not a legal transition. Order #23
   is still recorded FAILED while Razorpay holds a real captured ₹275 payment.
2. A repeated failure callback raised InvalidTransitionError on FAILED →
   FAILED, which surfaced to the browser as an unexplained 500.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.cart import Cart, CartItem
from app.models.order import Order
from app.orders import service as order_service
from app.orders.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    OrderStatus,
    can_transition,
)
from app.repositories import product_repo


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _failed_order(db) -> Order:
    product = product_repo.upsert(
        db,
        {
            "sku": "GRO-001",
            "name": "Atta 5kg",
            "brand": "Aashirvaad",
            "category": "groceries",
            "price_paise": 27500,
            "cost_paise": 19000,
            "unit": "5 kg pack",
            "stock": 40,
            "description": "flour",
            "tags": [],
        },
    )
    cart = Cart(user_id="user_demo", status="active")
    db.add(cart)
    db.flush()
    db.add(
        CartItem(cart_id=cart.id, product_id=product.id, quantity=1, unit_price_paise=product.price_paise, user_id="user_demo")
    )
    db.flush()
    db.refresh(cart)

    order = order_service.create_or_get_order(db, user_id="user_demo", session_id="s-recover", cart=cart).order
    order.status = OrderStatus.AWAITING_CONFIRMATION.value
    order.razorpay_order_id = "order_test_recover"
    db.flush()

    order_service.mark_failed(db, order, error_code="BAD_REQUEST_ERROR", error_description="UPI PIN incorrect")
    assert order.status == OrderStatus.FAILED.value
    return order


# --- transition table ------------------------------------------------------


def test_failed_can_now_reach_paid():
    assert can_transition(OrderStatus.FAILED, OrderStatus.PAID)


def test_paid_is_still_terminal():
    """The guard that must NOT be relaxed: a stale or duplicated failure
    callback must never downgrade a payment whose signature we verified."""
    assert ALLOWED_TRANSITIONS[OrderStatus.PAID] == frozenset()
    assert not can_transition(OrderStatus.PAID, OrderStatus.FAILED)


# --- FAILED → PAID ---------------------------------------------------------


def test_late_verified_success_recovers_a_failed_order(db):
    """Razorpay Checkout can report failure then success within one session.
    Razorpay is the authority on whether money moved."""
    order = _failed_order(db)

    order_service.mark_paid(
        db, order, razorpay_payment_id="pay_real_late", method="upi", raw_response={"late": True}
    )

    assert order.status == OrderStatus.PAID.value
    captured = [p for p in order.payments if p.status == "captured"]
    assert len(captured) == 1
    assert captured[0].razorpay_payment_id == "pay_real_late"


def test_recovery_is_written_to_the_audit_trail(db):
    """A silent FAILED → PAID would be precisely the kind of unexplained state
    change this project exists to prevent."""
    from app.models.audit_event import AuditEvent

    order = _failed_order(db)
    order_service.mark_paid(db, order, razorpay_payment_id="pay_real_late", method="upi", raw_response=None)

    events = db.query(AuditEvent).filter(AuditEvent.event_type == "payment_recovered_after_failure").all()
    assert len(events) == 1
    assert "pay_real_late" in events[0].reason
    assert events[0].decision == "ALLOW"


def test_a_clean_payment_logs_no_recovery_event(db):
    """The recovery event must mean something — it should not fire on an
    ordinary AWAITING_CONFIRMATION → PAID."""
    from app.models.audit_event import AuditEvent

    order = _failed_order(db)
    order.status = OrderStatus.AWAITING_CONFIRMATION.value
    db.flush()

    order_service.mark_paid(db, order, razorpay_payment_id="pay_clean", method="upi", raw_response=None)

    assert db.query(AuditEvent).filter(AuditEvent.event_type == "payment_recovered_after_failure").count() == 0


# --- FAILED → FAILED -------------------------------------------------------


def test_repeat_failure_callback_does_not_raise(db):
    """This raised InvalidTransitionError, which reached the browser as a
    500 with no CORS headers — reported to the user as "could not reach the
    API" for a backend that was answering. See tests/test_error_cors.py."""
    order = _failed_order(db)

    order_service.mark_failed(db, order, error_code="BAD_REQUEST_ERROR", error_description="reported twice")

    assert order.status == OrderStatus.FAILED.value
    # Both attempts are still recorded; only the redundant transition is skipped.
    assert len([p for p in order.payments if p.status == "failed"]) == 2


def test_repeat_failure_after_payment_still_never_downgrades(db):
    order = _failed_order(db)
    order_service.mark_paid(db, order, razorpay_payment_id="pay_real_late", method="upi", raw_response=None)

    order_service.mark_failed(db, order, error_code="STALE", error_description="stale callback arriving late")

    assert order.status == OrderStatus.PAID.value


def test_terminal_cancelled_still_rejects_payment(db):
    """Relaxing FAILED must not have relaxed anything else."""
    order = _failed_order(db)
    order.status = OrderStatus.CANCELLED.value
    db.flush()

    with pytest.raises(InvalidTransitionError):
        order_service.mark_paid(db, order, razorpay_payment_id="pay_x", method="upi", raw_response=None)
