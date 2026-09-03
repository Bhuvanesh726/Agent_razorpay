"""Layer 4.7 definition-of-done tests, exercised through the real HTTP/routing
layer (TestClient + SecureAPIRoute), not by calling router functions directly
— several of these (default-deny, JWT/agent-key resolution) only exist at
that layer and would be invisible to a direct function call.

Principal resolution (app/auth/principal.py) opens its own short-lived
SessionLocal() rather than using the request's Depends(get_db) session, so
the fixture below points BOTH at the same StaticPool in-memory sqlite engine
— otherwise a JWT/agent-key created by a test would be invisible to
resolve_principal's own connection.
"""

import json
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.principal as principal_module
from app.auth.routing import SecureAPIRoute
from app.auth.security import create_access_token, generate_agent_key, hash_agent_key
from app.database import Base, get_db
from app.llm.gateway import GatewayResult
from app.llm.gateway import ToolCall as GatewayToolCall
from app.main import app
from app.models.agent_credential import AgentCredential
from app.models.user import User
from app.repositories import product_repo


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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


def _make_agent_credential(
    session_factory,
    *,
    owner_user_id: str,
    scopes: list[str],
    spend_limit_paise: int,
    status: str = "ACTIVE",
    spent_paise: int = 0,
) -> str:
    raw_key = generate_agent_key()
    db = session_factory()
    try:
        cred = AgentCredential(
            owner_user_id=owner_user_id,
            name="test-agent",
            key_hash=hash_agent_key(raw_key),
            delivery_mode="EXTERNAL",
            scopes=scopes,
            spend_limit_paise=spend_limit_paise,
            spent_paise=spent_paise,
            status=status,
        )
        db.add(cred)
        db.commit()
    finally:
        db.close()
    return raw_key


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


def _add_to_cart_response() -> GatewayResult:
    return GatewayResult(
        content=None,
        tool_calls=[
            GatewayToolCall(
                id="call_1", name="add_to_cart", arguments_raw=json.dumps({"sku": "PET-001", "quantity": 1})
            )
        ],
        model_used="test-model",
        fallback_used=False,
        latency_ms=1,
    )


def _final_response(content: str) -> GatewayResult:
    return GatewayResult(content=content, tool_calls=[], model_used="test-model", fallback_used=False, latency_ms=1)


# --- 1. Buyer cannot reach merchant endpoints ---


def test_buyer_cannot_reach_merchant_campaigns_endpoint(client, session_factory):
    _make_user(session_factory, user_id="buyer-1", email="buyer1@example.test", role="BUYER")
    token = _jwt_for("buyer-1", "buyer1@example.test", "BUYER")

    resp = client.get("/api/campaigns", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_merchant_can_reach_merchant_campaigns_endpoint(client, session_factory):
    _make_user(session_factory, user_id="merchant-1", email="merchant1@example.test", role="MERCHANT")
    token = _jwt_for("merchant-1", "merchant1@example.test", "MERCHANT")

    resp = client.get("/api/campaigns", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# --- 2. cost_paise never appears in a buyer-facing response ---


def test_cost_paise_absent_from_product_and_catalog_responses(client, session_factory):
    """Product.cost_paise (COGS, merchant margin data) must never leak
    through the buyer/agent-facing product or catalog-feed endpoints — these
    require no auth at all (public browsing), so no principal is needed to
    hit them."""
    _seed_pedigree(session_factory)

    products = client.get("/api/products").json()
    assert "cost_paise" not in json.dumps(products)

    feed = client.get("/api/catalog/feed").json()
    assert "cost_paise" not in json.dumps(feed)


# --- 3. Agent blocked at credential limit even when session budget would allow more ---


def test_agent_blocked_at_credential_spend_limit_despite_higher_session_budget(client, session_factory):
    _make_user(session_factory, user_id="buyer-2", email="buyer2@example.test", role="BUYER")
    _seed_pedigree(session_factory)
    raw_key = _make_agent_credential(
        session_factory,
        owner_user_id="buyer-2",
        scopes=["search_products", "get_product", "add_to_cart", "view_cart"],
        spend_limit_paise=50_000,  # below the 74000-paise product price
    )

    scripted = iter([_add_to_cart_response(), _final_response("Sorry, that would exceed your agent's spend limit.")])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        resp = client.post(
            "/api/agent/chat",
            headers={"X-Agent-Key": raw_key},
            json={"session_id": "sess-agent-limit", "message": "buy dog food", "budget_paise": 1_000_000},
        )
    assert resp.status_code == 200

    db = session_factory()
    try:
        from app.audit.service import AuditService

        trail = AuditService().get_trail(db, "sess-agent-limit")
        denials = [e for e in trail if e.decision == "DENY" and e.rule_name == "AgentSpendLimitRule"]
        assert len(denials) == 1

        cred = db.query(AgentCredential).filter_by(owner_user_id="buyer-2").first()
        assert cred.spent_paise == 0  # nothing was actually added
    finally:
        db.close()


# --- 4. Revoked credential denied immediately ---


def test_revoked_credential_denied_immediately(client, session_factory):
    _make_user(session_factory, user_id="buyer-3", email="buyer3@example.test", role="BUYER")
    _seed_pedigree(session_factory)
    raw_key = _make_agent_credential(
        session_factory,
        owner_user_id="buyer-3",
        scopes=["search_products", "get_product", "add_to_cart", "view_cart"],
        spend_limit_paise=1_000_000,
        status="REVOKED",
    )

    scripted = iter([_add_to_cart_response(), _final_response("This agent's credential has been revoked.")])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        resp = client.post(
            "/api/agent/chat",
            headers={"X-Agent-Key": raw_key},
            json={"session_id": "sess-agent-revoked", "message": "buy dog food", "budget_paise": 500_000},
        )
    # Authentication succeeds (the key hash is real) — the denial happens at
    # the policy layer, not as a bare 401.
    assert resp.status_code == 200

    db = session_factory()
    try:
        from app.audit.service import AuditService

        trail = AuditService().get_trail(db, "sess-agent-revoked")
        denials = [e for e in trail if e.decision == "DENY" and e.rule_name == "RevokedCredentialRule"]
        assert len(denials) == 1
    finally:
        db.close()


# --- 5. Agent cannot call a tool outside its scopes ---


def test_agent_blocked_outside_declared_scopes(client, session_factory):
    _make_user(session_factory, user_id="buyer-4", email="buyer4@example.test", role="BUYER")
    _seed_pedigree(session_factory)
    raw_key = _make_agent_credential(
        session_factory,
        owner_user_id="buyer-4",
        scopes=["search_products", "get_product"],  # deliberately missing add_to_cart
        spend_limit_paise=1_000_000,
    )

    scripted = iter([_add_to_cart_response(), _final_response("This agent isn't allowed to add items to cart.")])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        resp = client.post(
            "/api/agent/chat",
            headers={"X-Agent-Key": raw_key},
            json={"session_id": "sess-agent-scope", "message": "buy dog food", "budget_paise": 500_000},
        )
    assert resp.status_code == 200

    db = session_factory()
    try:
        from app.audit.service import AuditService

        trail = AuditService().get_trail(db, "sess-agent-scope")
        denials = [e for e in trail if e.decision == "DENY" and e.rule_name == "AgentScopeRule"]
        assert len(denials) == 1
    finally:
        db.close()


# --- 6. User A cannot read user B's agents, audit events, or orders ---


def test_user_cannot_list_or_read_another_users_agent(client, session_factory):
    _make_user(session_factory, user_id="buyer-a", email="a@example.test", role="BUYER")
    _make_user(session_factory, user_id="buyer-b", email="b@example.test", role="BUYER")
    _make_agent_credential(session_factory, owner_user_id="buyer-a", scopes=["search_products"], spend_limit_paise=1000)

    token_b = _jwt_for("buyer-b", "b@example.test", "BUYER")
    listing = client.get("/api/agents", headers={"Authorization": f"Bearer {token_b}"})
    assert listing.status_code == 200
    assert listing.json() == []  # B sees none of A's agents

    db = session_factory()
    try:
        cred_id = db.query(AgentCredential).filter_by(owner_user_id="buyer-a").first().id
    finally:
        db.close()

    detail = client.get(f"/api/agents/{cred_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert detail.status_code == 404


def test_user_cannot_read_another_users_audit_trail(client, session_factory):
    _make_user(session_factory, user_id="buyer-c", email="c@example.test", role="BUYER")
    _make_user(session_factory, user_id="buyer-d", email="d@example.test", role="BUYER")
    token_c = _jwt_for("buyer-c", "c@example.test", "BUYER")
    token_d = _jwt_for("buyer-d", "d@example.test", "BUYER")

    # buyer-c creates a session of their own via the chat endpoint
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: _final_response("hi")):
        client.post(
            "/api/agent/chat",
            headers={"Authorization": f"Bearer {token_c}"},
            json={"session_id": "sess-owned-by-c", "message": "hello", "budget_paise": 100_000},
        )

    own = client.get("/api/audit/sess-owned-by-c", headers={"Authorization": f"Bearer {token_c}"})
    assert own.status_code == 200

    other = client.get("/api/audit/sess-owned-by-c", headers={"Authorization": f"Bearer {token_d}"})
    assert other.status_code == 404


def test_user_cannot_read_another_users_order_via_payments(client, session_factory):
    from app.models.cart import Cart
    from app.models.order import Order

    db = session_factory()
    try:
        cart = Cart(user_id="buyer-e", status="checked_out")
        db.add(cart)
        db.flush()
        db.add(
            Order(
                user_id="buyer-e",
                session_id="sess-e",
                cart_id=cart.id,
                razorpay_order_id="order_owned_by_e",
                amount_paise=1000,
                currency="INR",
                status="AWAITING_CONFIRMATION",
                idempotency_key="idem-e-1",
            )
        )
        db.commit()
    finally:
        db.close()

    _make_user(session_factory, user_id="buyer-f", email="f@example.test", role="BUYER")
    token_f = _jwt_for("buyer-f", "f@example.test", "BUYER")

    resp = client.post(
        "/api/payments/verify",
        headers={"Authorization": f"Bearer {token_f}"},
        json={"razorpay_order_id": "order_owned_by_e", "razorpay_payment_id": "pay_x", "razorpay_signature": "0" * 64},
    )
    assert resp.status_code == 404


# --- 7. EMBEDDED key never returned by any endpoint ---


def test_embedded_agent_key_never_returned(client, session_factory):
    _make_user(session_factory, user_id="buyer-g", email="g@example.test", role="BUYER")
    token = _jwt_for("buyer-g", "g@example.test", "BUYER")

    create_resp = client.post(
        "/api/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "my embedded agent",
            "delivery_mode": "EMBEDDED",
            "scopes": ["search_products", "add_to_cart"],
            "spend_limit_paise": 50_000,
            "standing_instruction": "Buy dog food if it's on sale.",
        },
    )
    assert create_resp.status_code == 200
    body = create_resp.json()
    assert body["key"] is None
    assert "agentkey_" not in json.dumps(body)

    listing = client.get("/api/agents", headers={"Authorization": f"Bearer {token}"})
    assert "agentkey_" not in json.dumps(listing.json())
    assert "key" not in listing.json()[0]

    detail = client.get(f"/api/agents/{body['id']}", headers={"Authorization": f"Bearer {token}"})
    assert "agentkey_" not in json.dumps(detail.json())
    assert "key" not in detail.json()


def test_external_agent_key_returned_exactly_once_at_creation(client, session_factory):
    _make_user(session_factory, user_id="buyer-h", email="h@example.test", role="BUYER")
    token = _jwt_for("buyer-h", "h@example.test", "BUYER")

    create_resp = client.post(
        "/api/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "my external agent",
            "delivery_mode": "EXTERNAL",
            "scopes": ["search_products", "add_to_cart"],
            "spend_limit_paise": 50_000,
        },
    )
    body = create_resp.json()
    assert body["key"].startswith("agentkey_")

    # But it's never returned again — not on list, not on detail.
    listing = client.get("/api/agents", headers={"Authorization": f"Bearer {token}"})
    assert "agentkey_" not in json.dumps(listing.json())

    detail = client.get(f"/api/agents/{body['id']}", headers={"Authorization": f"Bearer {token}"})
    assert "agentkey_" not in json.dumps(detail.json())


# --- 8. Endpoint with no declared auth requirement fails closed ---


def test_endpoint_with_no_auth_marker_fails_closed():
    """A standalone app, isolated from the real one, proving the SecureAPIRoute
    mechanism itself: a route registered with route_class=SecureAPIRoute but
    with neither @public nor @requires(...) is unreachable for everyone,
    with no header or credential able to get past it."""
    isolated_app = FastAPI()
    router = APIRouter(route_class=SecureAPIRoute)

    @router.get("/api/unmarked")
    def unmarked_endpoint() -> dict:
        return {"should": "never be reached"}

    isolated_app.include_router(router)
    isolated_client = TestClient(isolated_app)

    resp = isolated_client.get("/api/unmarked")
    assert resp.status_code == 403
