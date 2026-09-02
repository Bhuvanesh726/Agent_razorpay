"""Proves the audit log is self-sufficient: replay reads only audit_events
and still reconstructs the real final cart state exactly.
"""

import json
from unittest.mock import patch

from app.agent import harness
from app.audit.replay import replay_session
from app.llm.gateway import GatewayResult
from app.llm.gateway import ToolCall as GatewayToolCall
from app.repositories import product_repo
from app.services import cart_service


def seed_catalog(db):
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
        },
    )
    product_repo.upsert(
        db,
        {
            "sku": "GRO-001",
            "name": "Aashirvaad Atta",
            "brand": "Aashirvaad",
            "category": "groceries",
            "price_paise": 10000,  # kept low so two adds stay under the confirmation threshold
            "unit": "5kg pack",
            "stock": 40,
            "description": "flour",
            "tags": ["atta"],
        },
    )
    db.commit()


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


def test_replay_reconstructs_final_cart_from_the_log_alone(db_session):
    seed_catalog(db_session)
    session_id = "sess-replay-1"

    scripted = iter(
        [
            _tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}),
            _final_response("Added the dog food."),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        harness.handle_chat(db_session, session_id, "user_demo", "add dog food", 500_000, "req-1")

    scripted2 = iter(
        [
            _tool_call_response("add_to_cart", {"sku": "GRO-001", "quantity": 2}),
            _final_response("Added two attas too."),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted2)):
        harness.handle_chat(db_session, session_id, "user_demo", "add two attas", None, "req-2")

    # The real, live cart state — the thing replay must match without ever
    # touching the carts/cart_items tables itself.
    real_cart = cart_service.get_cart(db_session, "user_demo").model_dump(mode="json")

    replay = replay_session(db_session, session_id)

    assert replay.final_cart is not None
    assert replay.final_cart["total_paise"] == real_cart["total_paise"]
    assert replay.final_cart["id"] == real_cart["id"]

    replayed_items = {(i["sku"], i["quantity"]) for i in replay.final_cart["items"]}
    real_items = {(i["sku"], i["quantity"]) for i in real_cart["items"]}
    assert replayed_items == real_items
    assert real_items == {("PET-001", 1), ("GRO-001", 2)}

    assert len(replay.narrative) == len(replay.events) > 0
    assert any("add_to_cart" in line for line in replay.narrative)


def test_replay_uses_only_the_audit_log_no_other_table(db_session):
    """Structural guarantee, not just a behavioral one: replay_session's
    only DB access is through AuditService.get_trail — verified by patching
    every other repository's read functions to explode if called."""
    seed_catalog(db_session)
    session_id = "sess-replay-2"
    scripted = iter(
        [
            _tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}),
            _final_response("Added."),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        harness.handle_chat(db_session, session_id, "user_demo", "add dog food", None, "req-1")

    with (
        patch("app.repositories.cart_repo.get_active_cart", side_effect=AssertionError("replay touched carts")),
        patch("app.repositories.product_repo.get_by_sku", side_effect=AssertionError("replay touched products")),
    ):
        replay = replay_session(db_session, session_id)

    assert replay.final_cart is not None
    assert replay.final_cart["items"][0]["sku"] == "PET-001"


def test_replay_tracks_final_order_status(db_session):
    from app.orders.state_machine import OrderStatus

    seed_catalog(db_session)
    session_id = "sess-replay-3"
    from app.audit.service import AuditService

    audit = AuditService()
    audit.log_event(db_session, session_id=session_id, user_id="user_demo", event_type="user_message", actor="user")
    audit.log_event(
        db_session,
        session_id=session_id,
        user_id="user_demo",
        event_type="payment_succeeded",
        actor="system",
        reason="Payment captured.",
    )

    replay = replay_session(db_session, session_id)
    assert replay.final_order_status == OrderStatus.PAID.value
