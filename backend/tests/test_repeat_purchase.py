"""Buying the same basket twice must produce two orders.

The idempotency key was originally content + amount only, on the reasoning
that paying empties the cart so a later purchase would differ. A fresh cart
refilled with the same items has identical contents, so the second purchase
collided with the first and was refused with "this exact cart has already
been paid for" — permanently, for any basket a buyer ever repeated. See
Failures.md and app/orders/idempotency.py.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.cart import CartItem
from app.orders import service as order_service
from app.orders.state_machine import OrderStatus
from app.repositories import cart_repo, product_repo

USER = "user_demo"


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


@pytest.fixture()
def product(db):
    p = product_repo.upsert(
        db,
        {
            "sku": "GRO-001",
            "name": "Atta 5kg",
            "brand": "Aashirvaad",
            "category": "groceries",
            "price_paise": 27500,
            "cost_paise": 19000,
            "unit": "5 kg pack",
            "stock": 99,
            "description": "flour",
            "tags": [],
        },
    )
    db.commit()
    return p


def _fill_cart_and_order(db, product, *, quantity=1):
    cart = cart_repo.get_or_create_active_cart(db, USER)
    db.add(
        CartItem(
            cart_id=cart.id,
            product_id=product.id,
            quantity=quantity,
            unit_price_paise=product.price_paise,
            user_id=USER,
        )
    )
    db.flush()
    db.refresh(cart)
    return order_service.create_or_get_order(db, user_id=USER, session_id="s1", cart=cart)


def _pay(db, order, payment_id):
    order.status = OrderStatus.AWAITING_CONFIRMATION.value
    db.flush()
    order_service.mark_paid(db, order, razorpay_payment_id=payment_id, method="upi", raw_response=None)
    db.commit()


def test_the_same_basket_can_be_bought_again(db, product):
    first = _fill_cart_and_order(db, product)
    _pay(db, first.order, "pay_1")

    second = _fill_cart_and_order(db, product)
    db.commit()

    assert second.was_duplicate is False, "a genuine re-purchase was merged into the earlier paid order"
    assert second.order.id != first.order.id
    assert second.order.status == OrderStatus.PENDING.value


def test_retrying_the_same_unpaid_cart_still_collapses_to_one_order(db, product):
    """The behaviour idempotency exists for, and which the fix must not lose:
    a double-click on Confirm is one order, not two."""
    first = _fill_cart_and_order(db, product)
    db.commit()

    cart = cart_repo.get_active_cart(db, USER)
    again = order_service.create_or_get_order(db, user_id=USER, session_id="s1", cart=cart)

    assert again.was_duplicate is True
    assert again.order.id == first.order.id


def test_a_different_basket_is_a_different_order(db, product):
    first = _fill_cart_and_order(db, product)
    _pay(db, first.order, "pay_1")

    second = _fill_cart_and_order(db, product, quantity=3)
    db.commit()

    assert second.order.id != first.order.id
    assert second.order.amount_paise == product.price_paise * 3
