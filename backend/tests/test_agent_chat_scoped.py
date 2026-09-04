"""Layer 5c definition-of-done tests: interactive chat scoped to a specific
EMBEDDED AgentCredential (app/auth/credentials_router.py's chat/confirm/
quick-buy endpoints), reusing run_agent()'s principal-construction pattern
but for a real multi-turn conversation. Same TestClient + session_factory
fixture pattern as tests/test_principals_auth.py.
"""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.principal as principal_module
from app.auth.security import create_access_token, generate_agent_key, hash_agent_key
from app.database import Base, get_db
from app.llm.gateway import GatewayResult
from app.llm.gateway import ToolCall as GatewayToolCall
from app.main import app
from app.models.agent_credential import AgentCredential
from app.models.user import User
from app.payments.gateway import RazorpayOrder
from app.repositories import product_repo


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


def _make_embedded_agent(
    session_factory, *, owner_user_id: str, scopes: list[str], spend_limit_paise: int
) -> str:
    db = session_factory()
    try:
        cred = AgentCredential(
            owner_user_id=owner_user_id,
            name="test-embedded-agent",
            key_hash=hash_agent_key(generate_agent_key()),
            delivery_mode="EMBEDDED",
            scopes=scopes,
            spend_limit_paise=spend_limit_paise,
            status="ACTIVE",
        )
        db.add(cred)
        db.commit()
        db.refresh(cred)
        return cred.id
    finally:
        db.close()


def _seed_salt(session_factory) -> None:
    db = session_factory()
    try:
        product_repo.upsert(
            db,
            {
                "sku": "GRO-004",
                "name": "Tata Salt Iodised 1kg",
                "brand": "Tata",
                "category": "groceries",
                "price_paise": 2800,
                "unit": "1 kg pack",
                "stock": 100,
                "description": "iodised salt",
                "tags": ["salt"],
                "cost_paise": 1500,
            },
        )
        db.commit()
    finally:
        db.close()


def _tool_call_response(name: str, arguments: dict) -> GatewayResult:
    return GatewayResult(
        content=None,
        tool_calls=[GatewayToolCall(id="call_1", name=name, arguments_raw=json.dumps(arguments))],
        model_used="test-model",
        fallback_used=False,
        latency_ms=1,
    )


def _final_response(content: str) -> GatewayResult:
    return GatewayResult(content=content, tool_calls=[], model_used="test-model", fallback_used=False, latency_ms=1)


# --- Interactive chat is scoped to the credential's own scopes ---


def test_chat_with_agent_denies_out_of_scope_tool_call(client, session_factory):
    _seed_salt(session_factory)
    _make_user(session_factory, user_id="buyer-scoped-1", email="scoped1@example.test", role="BUYER")
    token = _jwt_for("buyer-scoped-1", "scoped1@example.test", "BUYER")
    # Scoped to search only — no add_to_cart.
    cred_id = _make_embedded_agent(
        session_factory, owner_user_id="buyer-scoped-1", scopes=["search_products"], spend_limit_paise=100_000
    )

    scripted = iter(
        [
            _tool_call_response("add_to_cart", {"sku": "GRO-004", "quantity": 1}),
            _final_response("I can't add that for you."),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        res = client.post(
            f"/api/agents/{cred_id}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"session_id": "sess-scoped-1", "message": "add the salt"},
        )
    assert res.status_code == 200

    from app.audit.service import AuditService

    db = session_factory()
    try:
        trail = AuditService().get_trail(db, "sess-scoped-1")
    finally:
        db.close()
    denials = [e for e in trail if e.decision == "DENY" and e.rule_name == "AgentScopeRule"]
    assert len(denials) == 1
    assert "not scoped to call 'add_to_cart'" in denials[0].reason


def test_chat_with_agent_rejects_another_buyers_credential(client, session_factory):
    _make_user(session_factory, user_id="buyer-scoped-a", email="scoped-a@example.test", role="BUYER")
    _make_user(session_factory, user_id="buyer-scoped-b", email="scoped-b@example.test", role="BUYER")
    token_b = _jwt_for("buyer-scoped-b", "scoped-b@example.test", "BUYER")
    cred_id = _make_embedded_agent(
        session_factory, owner_user_id="buyer-scoped-a", scopes=["search_products"], spend_limit_paise=100_000
    )

    res = client.post(
        f"/api/agents/{cred_id}/chat",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"session_id": "sess-scoped-x", "message": "hi"},
    )
    assert res.status_code == 404


# --- Quick-buy: one-click confirm-to-pay, fully policy-checked ---


def test_quick_buy_completes_payment_autonomously(client, session_factory):
    """The whole point of a bounded agent: once the human has granted it
    scopes and a spend limit, a purchase inside that limit completes on its
    own — no Razorpay Checkout popup, no second confirmation. The order
    comes back already PAID, with a real Payment row behind it."""
    _seed_salt(session_factory)
    _make_user(session_factory, user_id="buyer-qb-1", email="qb1@example.test", role="BUYER")
    token = _jwt_for("buyer-qb-1", "qb1@example.test", "BUYER")
    cred_id = _make_embedded_agent(
        session_factory,
        owner_user_id="buyer-qb-1",
        scopes=["add_to_cart", "initiate_payment"],
        spend_limit_paise=100_000,
    )

    with patch(
        "app.orders.service.gateway.create_order",
        return_value=RazorpayOrder(razorpay_order_id="order_qb_1", amount_paise=2800, currency="INR", receipt="r-1"),
    ):
        res = client.post(
            f"/api/agents/{cred_id}/quick-buy",
            headers={"Authorization": f"Bearer {token}"},
            json={"session_id": "sess-qb-1", "sku": "GRO-004", "quantity": 1},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["razorpay_order_id"] == "order_qb_1"
    assert body["amount_paise"] == 2800
    # Already paid by the time the caller gets a response — nothing left for
    # a human to do, which is what "autonomous within the limit" means.
    assert body["status"] == "PAID"

    from app.audit.service import AuditService
    from app.orders import repository as order_repo
    from app.orders.state_machine import OrderStatus

    db = session_factory()
    try:
        trail = AuditService().get_trail(db, "sess-qb-1")
        order = order_repo.list_by_user(db, "buyer-qb-1", limit=1)[0]
        assert OrderStatus(order.status) == OrderStatus.PAID
        captured = [p for p in order.payments if p.status == "captured"]
        assert len(captured) == 1
        assert captured[0].method == "agent_autonomous"
    finally:
        db.close()

    confirmations = [e for e in trail if e.event_type == "confirmation_approved"]
    assert len(confirmations) == 1
    assert confirmations[0].tool_args["confirmation_source"] == "product_card"
    assert any(e.event_type == "payment_succeeded" for e in trail)


def test_quick_buy_denies_out_of_scope(client, session_factory):
    _seed_salt(session_factory)
    _make_user(session_factory, user_id="buyer-qb-2", email="qb2@example.test", role="BUYER")
    token = _jwt_for("buyer-qb-2", "qb2@example.test", "BUYER")
    # No add_to_cart scope at all.
    cred_id = _make_embedded_agent(
        session_factory, owner_user_id="buyer-qb-2", scopes=["search_products"], spend_limit_paise=100_000
    )

    res = client.post(
        f"/api/agents/{cred_id}/quick-buy",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": "sess-qb-2", "sku": "GRO-004", "quantity": 1},
    )
    assert res.status_code == 400
    assert "not scoped to call 'add_to_cart'" in res.json()["detail"]


def test_quick_buy_denies_over_spend_limit(client, session_factory):
    _seed_salt(session_factory)
    _make_user(session_factory, user_id="buyer-qb-3", email="qb3@example.test", role="BUYER")
    token = _jwt_for("buyer-qb-3", "qb3@example.test", "BUYER")
    # Salt is ₹28.00 — a ₹10 limit can't cover it.
    cred_id = _make_embedded_agent(
        session_factory, owner_user_id="buyer-qb-3", scopes=["add_to_cart", "initiate_payment"], spend_limit_paise=1000
    )

    res = client.post(
        f"/api/agents/{cred_id}/quick-buy",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": "sess-qb-3", "sku": "GRO-004", "quantity": 1},
    )
    assert res.status_code == 400
    assert "exceeding its" in res.json()["detail"]


def test_quick_buy_rejects_external_credential(client, session_factory):
    """Interactive endpoints are EMBEDDED-only — an EXTERNAL credential's
    security model requires its raw key, which the buyer's own login
    doesn't substitute for."""
    _make_user(session_factory, user_id="buyer-qb-4", email="qb4@example.test", role="BUYER")
    token = _jwt_for("buyer-qb-4", "qb4@example.test", "BUYER")
    db = session_factory()
    try:
        cred = AgentCredential(
            owner_user_id="buyer-qb-4",
            name="external-agent",
            key_hash=hash_agent_key(generate_agent_key()),
            delivery_mode="EXTERNAL",
            scopes=["add_to_cart", "initiate_payment"],
            spend_limit_paise=100_000,
            status="ACTIVE",
        )
        db.add(cred)
        db.commit()
        db.refresh(cred)
        cred_id = cred.id
    finally:
        db.close()

    res = client.post(
        f"/api/agents/{cred_id}/quick-buy",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": "sess-qb-4", "sku": "GRO-004", "quantity": 1},
    )
    assert res.status_code == 404
