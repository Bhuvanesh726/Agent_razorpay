"""The safety property that matters about demo sign-in: outside
APP_ENV=development there is no way to obtain a token for a demo principal,
whatever the request asks for.

Same shape as tests/test_chaos_gate.py, because it is the same guarantee —
a demo affordance that a production config could switch on would be a
backdoor, so the gate is a property of the environment rather than a flag.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.principal as principal_module
from app.auth.security import decode_access_token
from app.database import Base, get_db
from app.main import app
from app.models.agent_credential import AgentCredential
from app.models.order import Order
from app.models.user import User
from app.orders.state_machine import OrderStatus
from app.repositories import product_repo
from app.testing import demo_login

# Every environment name that is not exactly "development" must refuse.
NON_DEVELOPMENT_ENVS = ["production", "staging", "prod", "Development", "DEVELOPMENT", ""]


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


def _seed_catalog(session_factory) -> None:
    db = session_factory()
    try:
        for sku, name, category, price in (
            ("GRO-001", "Aashirvaad Atta 5kg", "groceries", 27500),
            ("GRO-002", "India Gate Rice 5kg", "groceries", 64900),
            ("GRO-003", "Sunflower Oil 1L", "groceries", 15500),
            ("GRO-004", "Tata Salt 1kg", "groceries", 2800),
            ("DAI-001", "Amul Milk 1L", "dairy", 6600),
        ):
            product_repo.upsert(
                db,
                {
                    "sku": sku,
                    "name": name,
                    "brand": name.split()[0],
                    "category": category,
                    "price_paise": price,
                    "cost_paise": int(price * 0.7),
                    "unit": "pack",
                    "stock": 50,
                    "description": name,
                    "tags": [],
                },
            )
        db.commit()
    finally:
        db.close()


def _as_env(env: str):
    """Both modules read app_env through their own import of `settings`."""
    return patch("app.testing.demo_login.settings.app_env", env)


# --- the gate itself -------------------------------------------------------


def test_available_only_in_development():
    with _as_env("development"):
        assert demo_login.demo_login_available() is True
    for env in NON_DEVELOPMENT_ENVS:
        with _as_env(env):
            assert demo_login.demo_login_available() is False, env


@pytest.mark.parametrize("env", NON_DEVELOPMENT_ENVS)
@pytest.mark.parametrize("role", ["BUYER", "MERCHANT"])
def test_demo_login_refused_outside_development(client, env, role):
    """The actual safety guarantee: a well-formed request for either demo
    principal gets 404 in every non-development environment."""
    with _as_env(env):
        res = client.post("/api/auth/demo-login", json={"role": role})
    assert res.status_code == 404
    assert "token" not in res.json()


@pytest.mark.parametrize("env", NON_DEVELOPMENT_ENVS)
def test_no_demo_user_is_created_when_refused(client, session_factory, env):
    """A refused login must not leave the principals behind as a side effect
    — otherwise the rows would exist in production even though nothing can
    log in as them."""
    with _as_env(env):
        client.post("/api/auth/demo-login", json={"role": "BUYER"})

    db = session_factory()
    try:
        assert db.get(User, demo_login.DEMO_MERCHANT_ID) is None
        assert db.query(AgentCredential).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize("env", NON_DEVELOPMENT_ENVS)
def test_options_report_unavailable_outside_development(client, env):
    with _as_env(env):
        res = client.get("/api/auth/demo-login")
    assert res.status_code == 200
    assert res.json() == {"available": False, "principals": []}


def test_seed_script_skips_demo_state_outside_development(session_factory):
    """scripts/seed.py calls ensure_demo_environment() only behind the gate,
    so a production seed produces no demo merchant."""
    db = session_factory()
    try:
        with _as_env("production"):
            if demo_login.demo_login_available():  # pragma: no cover
                demo_login.ensure_demo_environment(db)
        assert db.get(User, demo_login.DEMO_MERCHANT_ID) is None
    finally:
        db.close()


# --- what it does when it IS available ------------------------------------


@pytest.mark.parametrize("role", ["BUYER", "MERCHANT"])
def test_demo_login_issues_a_usable_token_in_development(client, session_factory, role):
    _seed_catalog(session_factory)
    with _as_env("development"):
        res = client.post("/api/auth/demo-login", json={"role": role})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["role"] == role

        claims = decode_access_token(body["token"])
        assert claims is not None
        assert claims["role"] == role

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["type"] == role.lower()


def test_demo_buyer_lands_on_state_worth_looking_at(client, session_factory):
    """A reviewer signing in as the buyer should find an agent, order history
    in two different terminal states, and a non-empty browse-abandonment
    segment — an empty dashboard demonstrates nothing."""
    _seed_catalog(session_factory)
    with _as_env("development"):
        res = client.post("/api/auth/demo-login", json={"role": "BUYER"})
    assert res.status_code == 200

    db = session_factory()
    try:
        buyer = demo_login.demo_buyer()

        credentials = db.query(AgentCredential).filter(AgentCredential.owner_user_id == buyer.user_id).all()
        assert len(credentials) == 1
        assert credentials[0].status == "ACTIVE"
        assert "initiate_payment" in credentials[0].scopes

        orders = db.query(Order).filter(Order.user_id == buyer.user_id).all()
        assert len(orders) == 2
        assert {o.status for o in orders} == {OrderStatus.PAID.value, OrderStatus.FAILED.value}

        from app.campaigns.segmentation import compute_browse_abandonment_segment
        from datetime import datetime, timezone

        segment = compute_browse_abandonment_segment(db, datetime.now(timezone.utc))
        assert len(segment.members) > 0
    finally:
        db.close()


def test_demo_login_restores_a_role_clobbered_by_the_dev_switch(client, session_factory):
    """/api/dev/switch-role writes a new role straight onto the user row. A
    reviewer signed in as the demo merchant who clicks "Switch to buyer view"
    would otherwise leave that principal stuck as a BUYER forever, silently
    breaking the merchant demo. Signing in again must restore it."""
    _seed_catalog(session_factory)
    with _as_env("development"):
        assert client.post("/api/auth/demo-login", json={"role": "MERCHANT"}).status_code == 200

    db = session_factory()
    try:
        merchant = db.get(User, demo_login.DEMO_MERCHANT_ID)
        merchant.role = "BUYER"  # what the dev role switch does
        db.commit()
    finally:
        db.close()

    with _as_env("development"):
        res = client.post("/api/auth/demo-login", json={"role": "MERCHANT"})
    assert res.status_code == 200
    assert res.json()["role"] == "MERCHANT"

    db = session_factory()
    try:
        assert db.get(User, demo_login.DEMO_MERCHANT_ID).role == "MERCHANT"
    finally:
        db.close()


def test_demo_login_is_idempotent(client, session_factory):
    """A reviewer clicking the button twice must not double the seeded state."""
    _seed_catalog(session_factory)
    with _as_env("development"):
        assert client.post("/api/auth/demo-login", json={"role": "BUYER"}).status_code == 200
        assert client.post("/api/auth/demo-login", json={"role": "BUYER"}).status_code == 200

    db = session_factory()
    try:
        buyer = demo_login.demo_buyer()
        assert db.query(Order).filter(Order.user_id == buyer.user_id).count() == 2
        assert db.query(AgentCredential).filter(AgentCredential.owner_user_id == buyer.user_id).count() == 1
    finally:
        db.close()


def test_seeded_payment_id_is_labelled_as_simulated(client, session_factory):
    """Seeded history must not imply money moved through Razorpay. The
    frontend keys its "simulated capture" warning off this prefix — see
    docs/PAYMENT-REALITY.md."""
    _seed_catalog(session_factory)
    with _as_env("development"):
        client.post("/api/auth/demo-login", json={"role": "BUYER"})

    db = session_factory()
    try:
        paid = db.query(Order).filter(Order.status == OrderStatus.PAID.value).one()
        captured = [p for p in paid.payments if p.status == "captured"]
        assert len(captured) == 1
        assert captured[0].razorpay_payment_id.startswith("pay_demo")
    finally:
        db.close()
