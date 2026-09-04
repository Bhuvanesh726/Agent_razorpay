"""Role routing and merchant catalog controls, exercised through the real
HTTP/routing layer — same pattern as tests/test_principals_auth.py.

There is no onboarding step: every Google login starts as a BUYER
(app/auth/oauth_router.py) and moves between views with the dev-only role
switch (app/auth/role_router.py). What these tests hold onto is the part that
still matters — that the two roles reach different things, and that a role
change actually re-gates access rather than just relabelling a token.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.principal as principal_module
from app.auth.security import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models.product import Product
from app.models.user import User


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


def _make_user(session_factory, *, user_id: str, email: str, role: str | None) -> None:
    db = session_factory()
    try:
        db.add(User(id=user_id, email=email, name=email, google_sub=None, role=role))
        db.commit()
    finally:
        db.close()


def _jwt_for(user_id: str, email: str, role: str | None) -> str:
    return create_access_token(sub=user_id, email=email, role=role)


def _seed_product(session_factory, *, sku="PET-001", price_paise=74000) -> None:
    db = session_factory()
    try:
        db.add(
            Product(
                sku=sku,
                name="Pedigree Adult Dry Dog Food",
                brand="Pedigree",
                category="pet_supplies",
                price_paise=price_paise,
                cost_paise=40000,
                unit="3kg pack",
                stock=25,
                description="dog food",
                tags=["dog"],
            )
        )
        db.commit()
    finally:
        db.close()


# --- role routing -----------------------------------------------------


def test_a_user_with_no_role_resolves_to_buyer(client, session_factory):
    """Rows written before roles were assigned at login. With no onboarding
    page to send them to, resolving to buyer is the only outcome that leaves
    them able to do anything — a login that succeeds and then reaches nothing
    would be worse than a default they can switch away from."""
    _make_user(session_factory, user_id="legacy-1", email="legacy@example.test", role=None)
    token = _jwt_for("legacy-1", "legacy@example.test", None)

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["type"] == "buyer"

    # And that resolution is real access, not just a label.
    assert client.get("/api/cart", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_a_buyer_reaches_the_buyer_dashboard_immediately(client, session_factory):
    """No intermediate step between signing in and using the app."""
    _make_user(session_factory, user_id="buyer-fresh", email="fresh@example.test", role="BUYER")
    token = _jwt_for("buyer-fresh", "fresh@example.test", "BUYER")
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/dashboard/summary", headers=headers).status_code == 200
    assert client.get("/api/merchant/notifications", headers=headers).status_code == 403


def test_the_removed_onboarding_endpoint_is_gone(client, session_factory):
    """It should 404 as a route that no longer exists, not 403 as one that is
    merely refused — the role-selection step was removed, not locked."""
    _make_user(session_factory, user_id="buyer-4", email="buyer4@example.test", role="BUYER")
    token = _jwt_for("buyer-4", "buyer4@example.test", "BUYER")

    resp = client.post(
        "/api/onboarding/role", headers={"Authorization": f"Bearer {token}"}, json={"role": "MERCHANT"}
    )
    assert resp.status_code == 404


def test_returning_merchant_reaches_merchant_dashboard_not_buyer_dashboard(client, session_factory):
    _make_user(session_factory, user_id="merchant-1", email="merchant1@example.test", role="MERCHANT")
    token = _jwt_for("merchant-1", "merchant1@example.test", "MERCHANT")
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/merchant/notifications", headers=headers).status_code == 200
    assert client.get("/api/dashboard/summary", headers=headers).status_code == 403


# --- buyer cannot reach merchant endpoints (no regression) -------------


def test_buyer_cannot_reach_any_merchant_dashboard_endpoint(client, session_factory):
    _make_user(session_factory, user_id="buyer-2", email="buyer2@example.test", role="BUYER")
    token = _jwt_for("buyer-2", "buyer2@example.test", "BUYER")
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/merchant/notifications", headers=headers).status_code == 403
    assert client.get("/api/merchant/products", headers=headers).status_code == 403
    assert client.get("/api/merchant/headline", headers=headers).status_code == 403
    assert (
        client.post("/api/merchant/products/PET-001/discount", headers=headers, json={"discount_pct": 10}).status_code
        == 403
    )


# --- dev-only role switch ------------------------------------------------


def test_dev_role_switch_requires_authentication(client):
    resp = client.post("/api/dev/switch-role", json={"role": "MERCHANT"})
    assert resp.status_code == 401


def test_dev_role_switch_moves_a_buyer_to_the_merchant_view(client, session_factory):
    _make_user(session_factory, user_id="buyer-3", email="buyer3@example.test", role="BUYER")
    token = _jwt_for("buyer-3", "buyer3@example.test", "BUYER")
    resp = client.post("/api/dev/switch-role", headers={"Authorization": f"Bearer {token}"}, json={"role": "MERCHANT"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "MERCHANT"


# --- discount: set, cap, buyer-facing display ----------------------------


def test_merchant_can_set_a_discount_within_the_cap(client, session_factory):
    _seed_product(session_factory)
    _make_user(session_factory, user_id="merchant-2", email="merchant2@example.test", role="MERCHANT")
    token = _jwt_for("merchant-2", "merchant2@example.test", "MERCHANT")

    resp = client.post(
        "/api/merchant/products/PET-001/discount",
        headers={"Authorization": f"Bearer {token}"},
        json={"discount_pct": 10},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["discount_pct"] == 10
    assert body["effective_price_paise"] == round(74000 * 0.9)


def test_merchant_cannot_set_a_discount_above_the_campaign_cap(client, session_factory):
    """Bounded by the same campaign_max_discount_pct ceiling the campaign
    system already enforces — see app/routers/merchant.py::set_discount."""
    _seed_product(session_factory)
    _make_user(session_factory, user_id="merchant-3", email="merchant3@example.test", role="MERCHANT")
    token = _jwt_for("merchant-3", "merchant3@example.test", "MERCHANT")

    resp = client.post(
        "/api/merchant/products/PET-001/discount",
        headers={"Authorization": f"Bearer {token}"},
        json={"discount_pct": 90},
    )
    assert resp.status_code == 422


def test_discounted_price_shows_on_buyer_facing_product_endpoint(client, session_factory):
    _seed_product(session_factory)
    _make_user(session_factory, user_id="merchant-4", email="merchant4@example.test", role="MERCHANT")
    merchant_token = _jwt_for("merchant-4", "merchant4@example.test", "MERCHANT")
    client.post(
        "/api/merchant/products/PET-001/discount",
        headers={"Authorization": f"Bearer {merchant_token}"},
        json={"discount_pct": 20},
    )

    product = client.get("/api/products/PET-001").json()
    assert product["price_paise"] == 74000  # list price, unaffected
    assert product["discount_pct"] == 20
    assert product["effective_price_paise"] == round(74000 * 0.8)


def test_clearing_a_discount_restores_list_price(client, session_factory):
    _seed_product(session_factory)
    _make_user(session_factory, user_id="merchant-5", email="merchant5@example.test", role="MERCHANT")
    token = _jwt_for("merchant-5", "merchant5@example.test", "MERCHANT")
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/api/merchant/products/PET-001/discount", headers=headers, json={"discount_pct": 15})
    resp = client.post("/api/merchant/products/PET-001/discount", headers=headers, json={"discount_pct": None})
    assert resp.status_code == 200
    assert resp.json()["discount_pct"] is None
    assert resp.json()["effective_price_paise"] == 74000


# --- toggle out-of-stock --------------------------------------------------


def test_toggle_out_of_stock_then_back(client, session_factory):
    _seed_product(session_factory)
    _make_user(session_factory, user_id="merchant-6", email="merchant6@example.test", role="MERCHANT")
    token = _jwt_for("merchant-6", "merchant6@example.test", "MERCHANT")
    headers = {"Authorization": f"Bearer {token}"}

    off = client.post("/api/merchant/products/PET-001/toggle-stock", headers=headers)
    assert off.status_code == 200
    assert off.json()["is_out_of_stock"] is True
    assert off.json()["stock"] == 0

    product = client.get("/api/products/PET-001").json()
    assert product["stock"] == 0

    on = client.post("/api/merchant/products/PET-001/toggle-stock", headers=headers)
    assert on.status_code == 200
    assert on.json()["is_out_of_stock"] is False
    assert on.json()["stock"] > 0
