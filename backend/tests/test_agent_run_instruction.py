"""`POST /api/agents/{id}/run` takes a per-run instruction.

The instruction used to be fixed at credential creation, which meant an agent
created without one had no "Run now" at all. The body field added for this is
optional, so a caller that sends none still runs the stored
standing_instruction exactly as before.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.principal as principal_module
from app.auth.security import create_access_token, hash_agent_key
from app.database import Base, get_db
from app.main import app
from app.models.agent_credential import AgentCredential
from app.models.user import User

BUYER = "user_buyer"
STORED = "Buy dog food if it's on sale."


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


def _agent(session_factory, *, standing_instruction: str | None) -> str:
    db = session_factory()
    try:
        db.add(User(id=BUYER, email="buyer@example.test", name="Buyer", google_sub=None, role="BUYER"))
        cred = AgentCredential(
            owner_user_id=BUYER,
            name="Runner",
            key_hash=hash_agent_key("agentkey_runner"),
            delivery_mode="EMBEDDED",
            scopes=["search_products"],
            spend_limit_paise=50_000,
            status="ACTIVE",
            standing_instruction=standing_instruction,
        )
        db.add(cred)
        db.commit()
        return cred.id
    finally:
        db.close()


def _auth():
    return {"Authorization": f"Bearer {create_access_token(sub=BUYER, email='buyer@example.test', role='BUYER')}"}


def _captured_run(client, credential_id, json_body):
    """Runs the endpoint with the harness stubbed, returning the user_message
    it was actually handed."""
    seen = {}

    def fake_handle_chat(db, session_id, user_id, user_message, budget_paise, request_id):
        seen["message"] = user_message
        return type("R", (), {"reply": "done", "status": "ok", "cart": {}})()

    with patch("app.agent.harness.handle_chat", side_effect=fake_handle_chat):
        res = client.post(f"/api/agents/{credential_id}/run", headers=_auth(), **json_body)
    return res, seen


def test_per_run_instruction_is_what_gets_sent(client, session_factory):
    cred = _agent(session_factory, standing_instruction=STORED)

    res, seen = _captured_run(client, cred, {"json": {"instruction": "Buy 2kg of rice under 200"}})

    assert res.status_code == 200, res.text
    assert seen["message"] == "Buy 2kg of rice under 200"


def test_stored_instruction_is_the_fallback(client, session_factory):
    """Prefilled in the UI, and used verbatim when the caller sends nothing —
    so an agent with a standing instruction behaves as it always did."""
    cred = _agent(session_factory, standing_instruction=STORED)

    res, seen = _captured_run(client, cred, {"json": {"instruction": None}})

    assert res.status_code == 200
    assert seen["message"] == STORED


def test_a_body_less_call_still_works(client, session_factory):
    """The field is additive: callers that predate it send no body at all."""
    cred = _agent(session_factory, standing_instruction=STORED)

    res, seen = _captured_run(client, cred, {})

    assert res.status_code == 200
    assert seen["message"] == STORED


def test_an_agent_without_a_standing_instruction_is_now_runnable(client, session_factory):
    """The point of the change: this used to 422 with no way to run it."""
    cred = _agent(session_factory, standing_instruction=None)

    res, seen = _captured_run(client, cred, {"json": {"instruction": "Find me cheap atta"}})

    assert res.status_code == 200
    assert seen["message"] == "Find me cheap atta"


def test_blank_instruction_and_no_fallback_is_refused(client, session_factory):
    cred = _agent(session_factory, standing_instruction=None)

    res, _ = _captured_run(client, cred, {"json": {"instruction": "   "}})

    assert res.status_code == 422


def test_running_the_credential_does_not_rewrite_its_stored_instruction(client, session_factory):
    """A per-run instruction is for this run only — it must not quietly
    become the agent's standing instruction."""
    cred = _agent(session_factory, standing_instruction=STORED)

    _captured_run(client, cred, {"json": {"instruction": "one-off errand"}})

    db = session_factory()
    try:
        assert db.get(AgentCredential, cred).standing_instruction == STORED
    finally:
        db.close()
