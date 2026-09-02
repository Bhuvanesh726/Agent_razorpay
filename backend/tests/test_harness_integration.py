"""Integration tests for the harness loop, with the LLM gateway stubbed out.

These exercise real DB persistence (sessions, messages, audit trail) and real
tool dispatch, but make zero network calls — the model's responses are
scripted in advance, exactly as a flaky/free-tier model's tool calls might
look, including a hallucinated SKU and a budget-busting quantity.
"""

import json
from unittest.mock import patch

from app.agent import harness
from app.llm.gateway import GatewayResult
from app.llm.gateway import ToolCall as GatewayToolCall
from app.policy.engine import PolicyEngine
from app.policy.rules import ConfirmationThresholdRule
from app.repositories import product_repo


def seed_pedigree(db):
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


def test_hallucinated_sku_is_denied_end_to_end(db_session):
    seed_pedigree(db_session)
    scripted = iter(
        [
            _tool_call_response("add_to_cart", {"sku": "FAKE-999", "quantity": 1}),
            _final_response("That product doesn't seem to exist, sorry."),
        ]
    )

    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        result = harness.handle_chat(db_session, "sess-hallucinated", "user_demo", "add the fake widget", None, "req-1")

    assert result.status == "completed"
    assert result.cart["items"] == []  # nothing was actually added

    trail = harness._audit.get_trail(db_session, "sess-hallucinated")
    denials = [e for e in trail if e.decision == "DENY" and e.rule_name == "UnknownSkuRule"]
    assert len(denials) == 1
    assert "FAKE-999" in denials[0].reason


def test_spend_cap_holds_when_model_tries_to_exceed_it_end_to_end(db_session):
    seed_pedigree(db_session)
    # 2 * 74000 = 148000, over an 80000 budget, but well within stock (25) and
    # per-item/quantity limits — isolates SpendCapRule specifically.
    scripted = iter(
        [
            _tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 2}),
            _final_response("That would exceed your ₹800 budget, so I didn't add it."),
        ]
    )

    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        result = harness.handle_chat(
            db_session, "sess-budget", "user_demo", "add two bags of dog food", 80_000, "req-2"
        )

    assert result.status == "completed"
    assert result.cart["items"] == []

    trail = harness._audit.get_trail(db_session, "sess-budget")
    denials = [e for e in trail if e.decision == "DENY" and e.rule_name == "SpendCapRule"]
    assert len(denials) == 1


def test_allowed_add_executes_and_appears_in_cart(db_session):
    seed_pedigree(db_session)
    scripted = iter(
        [
            _tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}),
            _final_response("Added Pedigree dog food to your cart."),
        ]
    )

    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        result = harness.handle_chat(db_session, "sess-allowed", "user_demo", "add dog food", 80_000, "req-3")

    assert result.status == "completed"
    assert result.cart["total_paise"] == 74000
    assert result.cart["items"][0]["sku"] == "PET-001"

    trail = harness._audit.get_trail(db_session, "sess-allowed")
    executed = [e for e in trail if e.event_type == "tool_executed"]
    assert len(executed) == 1


def test_confirmation_threshold_halts_until_confirmed(db_session):
    seed_pedigree(db_session)
    # Within budget (80000) but above a lowered confirmation threshold, so this
    # specifically isolates ConfirmationThresholdRule from SpendCapRule.
    low_threshold_engine = PolicyEngine(rules=[ConfirmationThresholdRule(threshold_paise=1000)])
    scripted = iter([_tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1})])

    with (
        patch("app.agent.harness._policy", low_threshold_engine),
        patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)),
    ):
        result = harness.handle_chat(db_session, "sess-confirm", "user_demo", "add dog food", 80_000, "req-4")

    assert result.status == "awaiting_confirmation"
    assert result.pending["tool_name"] == "add_to_cart"
    assert result.pending["rule_name"] == "ConfirmationThresholdRule"
    # cart untouched until confirmed
    assert result.cart["items"] == []

    scripted_after = iter([_final_response("Great, it's added.")])
    with (
        patch("app.agent.harness._policy", low_threshold_engine),
        patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_after)),
    ):
        confirmed = harness.handle_confirm(db_session, "sess-confirm", "user_demo", True, "req-5")

    assert confirmed.status == "completed"
    assert confirmed.cart["total_paise"] == 74000
