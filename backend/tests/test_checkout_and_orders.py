"""Layer 5b definition-of-done tests: the manual "Buy Now" checkout path
(app/routers/checkout.py), buyer/merchant order history (app/routers/orders.py),
and real purchase-attribution on merchant notifications
(app/demand/aggregation.py::purchases_since). Exercised through the real
HTTP/routing layer (TestClient + SecureAPIRoute), same fixture pattern as
tests/test_principals_auth.py.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.principal as principal_module
from app.auth.security import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models.merchant_notification import MerchantNotification
from app.models.user import User
from app.orders import repository as order_repo
from app.orders.state_machine import OrderStatus
from app.payments.gateway import RazorpayOrder
from app.repositories import cart_repo, product_repo
from app.schemas.cart import CartItemCreate
from app.services import cart_service


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def client(session_factory, monkeypatch):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(principal_module, "SessionLocal", session_factory)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _make_user(session_factory, *, user_id: str, email: str, role: str) -> None:
    db = session_factory()
    try:
        db.add(User(id=user_id, email=email, name=email, google_sub=None, role=role))
        db.commit()
    finally:
        db.close()


def _jwt_for(user_id: str, email: str, role: str) -> str:
    return create_access_token(sub=user_id, email=email, role=role)


def _seed_pedigree(session_factory) -> None:
    db = session_factory()
    try:
        product_repo.upsert(
            db,
            {
                "sku": "PET-001",
                "name": "Pedigree Adult Dry Dog Food",
                "brand": "Pedigree",
                "category": "pet_supplies",
                "price_paise": 74000,
                "unit": "3kg pack",
                "stock": 25,
                "description": "dog food",
                "tags": ["dog"],
                "cost_paise": 40000,
            },
        )
        db.commit()
    finally:
        db.close()


def _pay_order(session_factory, *, user_id: str, sku: str, quantity: int, session_id: str, payment_id: str):
    """Bypasses the real Razorpay round-trip (already covered end-to-end by
    tests/test_payment_flow_integration.py) — creates a cart, an order, and
    marks it PAID directly via app/orders/service.py, so tests here can
    focus on what reads an already-PAID order rather than re-proving payment
    verification itself."""
    from app.orders import service as order_service

    db = session_factory()
    try:
        cart_service.add_item(db, user_id, CartItemCreate(sku=sku, quantity=quantity))
        cart = cart_repo.get_or_create_active_cart(db, user_id)
        creation = order_service.create_or_get_order(db, user_id=user_id, session_id=session_id, cart=cart)
        order = creation.order
        order.status = OrderStatus.AWAITING_CONFIRMATION.value
        order_repo.save(db, order)
        order_service.mark_paid(db, order, razorpay_payment_id=payment_id, method=None, raw_response=None)
    finally:
        db.close()


# --- Buy Now (manual checkout) ---


def test_buy_now_rejects_empty_cart(client, session_factory):
    _make_user(session_factory, user_id="buyer-checkout-1", email="checkout1@example.test", role="BUYER")
    token = _jwt_for("buyer-checkout-1", "checkout1@example.test", "BUYER")

    res = client.post(
        "/api/checkout/initiate",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": "sess-checkout-1"},
    )
    assert res.status_code == 400


def test_buy_now_happy_path_creates_awaiting_confirmation_order(client, session_factory):
    _seed_pedigree(session_factory)
    _make_user(session_factory, user_id="buyer-checkout-2", email="checkout2@example.test", role="BUYER")
    token = _jwt_for("buyer-checkout-2", "checkout2@example.test", "BUYER")

    add = client.post(
        "/api/cart/items",
        headers={"Authorization": f"Bearer {token}"},
        json={"sku": "PET-001", "quantity": 1},
    )
    assert add.status_code == 200

    with patch(
        "app.orders.service.gateway.create_order",
        return_value=RazorpayOrder(
            razorpay_order_id="order_test_buynow", amount_paise=74000, currency="INR", receipt="order-buynow"
        ),
    ):
        res = client.post(
            "/api/checkout/initiate",
            headers={"Authorization": f"Bearer {token}"},
            json={"session_id": "sess-checkout-2"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["razorpay_order_id"] == "order_test_buynow"
    assert body["amount_paise"] == 74000
    assert body["status"] == "AWAITING_CONFIRMATION"


# --- Order history: ownership and scoping ---


def test_buyer_sees_only_own_orders_merchant_sees_all(client, session_factory):
    _seed_pedigree(session_factory)
    _make_user(session_factory, user_id="buyer-orders-a", email="orders-a@example.test", role="BUYER")
    _make_user(session_factory, user_id="buyer-orders-b", email="orders-b@example.test", role="BUYER")
    _make_user(session_factory, user_id="merchant-orders", email="merchant-orders@example.test", role="MERCHANT")

    _pay_order(session_factory, user_id="buyer-orders-a", sku="PET-001", quantity=1, session_id="s-a", payment_id="pay-a")
    _pay_order(session_factory, user_id="buyer-orders-b", sku="PET-001", quantity=2, session_id="s-b", payment_id="pay-b")

    token_a = _jwt_for("buyer-orders-a", "orders-a@example.test", "BUYER")
    token_merchant = _jwt_for("merchant-orders", "merchant-orders@example.test", "MERCHANT")

    mine = client.get("/api/orders", headers={"Authorization": f"Bearer {token_a}"})
    assert mine.status_code == 200
    mine_body = mine.json()
    assert len(mine_body) == 1
    assert mine_body[0]["item_count"] == 1

    everyone = client.get("/api/merchant/orders", headers={"Authorization": f"Bearer {token_merchant}"})
    assert everyone.status_code == 200
    everyone_body = everyone.json()
    assert len(everyone_body) == 2
    emails = {row["buyer_email"] for row in everyone_body}
    assert emails == {"orders-a@example.test", "orders-b@example.test"}


def test_order_detail_ownership_and_merchant_access(client, session_factory):
    _seed_pedigree(session_factory)
    _make_user(session_factory, user_id="buyer-orders-c", email="orders-c@example.test", role="BUYER")
    _make_user(session_factory, user_id="buyer-orders-d", email="orders-d@example.test", role="BUYER")
    _make_user(session_factory, user_id="merchant-orders-2", email="merchant-orders-2@example.test", role="MERCHANT")

    _pay_order(session_factory, user_id="buyer-orders-c", sku="PET-001", quantity=1, session_id="s-c", payment_id="pay-c")

    db = session_factory()
    try:
        order_id = order_repo.list_by_user(db, "buyer-orders-c", limit=1)[0].id
    finally:
        db.close()

    token_owner = _jwt_for("buyer-orders-c", "orders-c@example.test", "BUYER")
    token_other = _jwt_for("buyer-orders-d", "orders-d@example.test", "BUYER")
    token_merchant = _jwt_for("merchant-orders-2", "merchant-orders-2@example.test", "MERCHANT")

    owner_view = client.get(f"/api/orders/{order_id}", headers={"Authorization": f"Bearer {token_owner}"})
    assert owner_view.status_code == 200
    assert owner_view.json()["items"] == [
        {
            "sku": "PET-001",
            "name": "Pedigree Adult Dry Dog Food",
            "quantity": 1,
            "unit_price_paise": 74000,
            "line_total_paise": 74000,
        }
    ]
    assert owner_view.json()["status"] == "PAID"

    other_view = client.get(f"/api/orders/{order_id}", headers={"Authorization": f"Bearer {token_other}"})
    assert other_view.status_code == 404

    merchant_view = client.get(f"/api/orders/{order_id}", headers={"Authorization": f"Bearer {token_merchant}"})
    assert merchant_view.status_code == 200


# --- Real purchase attribution on notifications ---


def test_notification_shows_real_purchase_attribution(client, session_factory):
    _seed_pedigree(session_factory)
    _make_user(session_factory, user_id="merchant-attr", email="merchant-attr@example.test", role="MERCHANT")
    _make_user(session_factory, user_id="buyer-attr", email="buyer-attr@example.test", role="BUYER")

    db = session_factory()
    try:
        db.add(
            MerchantNotification(
                type="UNMET_DEMAND",
                dedupe_key="unmet:pet_supplies:attr-test",
                evidence={"category": "pet_supplies", "distinct_buyers": 5, "active_buyers": 6},
                suggested_action="Stock more pet supplies.",
                status="ACTED",
                acted_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        db.commit()
    finally:
        db.close()

    _pay_order(session_factory, user_id="buyer-attr", sku="PET-001", quantity=2, session_id="s-attr", payment_id="pay-attr")

    token_merchant = _jwt_for("merchant-attr", "merchant-attr@example.test", "MERCHANT")
    listing = client.get("/api/merchant/notifications", headers={"Authorization": f"Bearer {token_merchant}"})
    assert listing.status_code == 200
    rows = listing.json()
    matching = [r for r in rows if r["evidence"].get("category") == "pet_supplies"]
    assert len(matching) == 1
    assert matching[0]["purchases_since_acted"] == 1
    assert matching[0]["revenue_since_acted_paise"] == 2 * 74000
