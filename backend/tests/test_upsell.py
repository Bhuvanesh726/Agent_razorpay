"""Integration tests for the bounded upsell agent — the LLM gateway is
stubbed (scripted tool calls) but the recommender, policy engine, audit
trail, and DB are all real. Mirrors the pattern in test_harness_integration.py
and test_payment_flow_integration.py.
"""

import json
from unittest.mock import patch

from app.agent import harness
from app.llm.gateway import GatewayResult
from app.llm.gateway import ToolCall as GatewayToolCall
from app.payments.gateway import RazorpayOrder
from app.repositories import product_repo
from app.upsell import state as upsell_state


def seed_pet_pairing(db):
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
            "sku": "PET-004",
            "name": "Pedigree Dentastix Dog Treats",
            "brand": "Pedigree",
            "category": "pet_supplies",
            "price_paise": 24900,
            "unit": "7-pack",
            "stock": 40,
            "description": "dog treats",
            "tags": ["dog", "treats"],
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


def test_upsell_offer_appears_after_a_relevant_add(db_session):
    seed_pet_pairing(db_session)
    scripted = iter(
        [
            _tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}),
            _final_response("Added the dog food. Would you also like the dentastix treats?"),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        result = harness.handle_chat(db_session, "sess-upsell-1", "user_demo", "add dog food", 500_000, "req-1")

    assert result.upsell is not None
    assert result.upsell["sku"] == "PET-004"
    assert result.upsell["price_paise"] == 24900

    trail = harness._audit.get_trail(db_session, "sess-upsell-1")
    proposed = [e for e in trail if e.event_type == "upsell_proposed"]
    assert len(proposed) == 1
    assert proposed[0].tool_args["sku"] == "PET-004"


def test_upsell_accepted_records_incremental_revenue(db_session):
    seed_pet_pairing(db_session)
    scripted_1 = iter([_tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}), _final_response("added")])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_1)):
        first = harness.handle_chat(db_session, "sess-upsell-2", "user_demo", "add dog food", 500_000, "req-1")
    assert first.upsell is not None

    scripted_2 = iter(
        [_tool_call_response("add_to_cart", {"sku": "PET-004", "quantity": 1}), _final_response("added the treats too")]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_2)):
        second = harness.handle_chat(db_session, "sess-upsell-2", "user_demo", "yes add it", None, "req-2")

    assert second.upsell is None  # resolved
    assert second.cart["total_paise"] == 74000 + 24900

    trail = harness._audit.get_trail(db_session, "sess-upsell-2")
    accepted = [e for e in trail if e.event_type == "upsell_accepted"]
    assert len(accepted) == 1
    assert accepted[0].tool_args == {"sku": "PET-004", "price_paise": 24900, "quantity": 1}

    totals = harness._audit.compute_totals(trail)
    assert totals["upsell_accepted_count"] == 1
    assert totals["upsell_incremental_revenue_paise"] == 24900


def test_upsell_declined_via_tool_and_offer_clears(db_session):
    seed_pet_pairing(db_session)
    scripted_1 = iter([_tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}), _final_response("added")])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_1)):
        first = harness.handle_chat(db_session, "sess-upsell-3", "user_demo", "add dog food", 500_000, "req-1")
    assert first.upsell is not None

    scripted_2 = iter([_tool_call_response("decline_upsell", {}), _final_response("no problem")])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_2)):
        second = harness.handle_chat(db_session, "sess-upsell-3", "user_demo", "no thanks", None, "req-2")

    assert second.upsell is None

    trail = harness._audit.get_trail(db_session, "sess-upsell-3")
    declined = [e for e in trail if e.event_type == "upsell_declined"]
    assert len(declined) == 1
    assert declined[0].actor == "user"
    assert declined[0].tool_args["sku"] == "PET-004"

    state = upsell_state.get_state(db_session, "sess-upsell-3")
    assert "PET-004" in state.declined_skus


def test_upsell_blocked_by_spend_cap_never_surfaced(db_session):
    """No special path: the same SpendCapRule that gates add_to_cart also
    gates a candidate upsell, and a blocked offer is never attached to the
    tool result the model sees."""
    seed_pet_pairing(db_session)
    # 74000 (base) fits an 80000 budget; +24900 for the upsell (98900) does not.
    scripted = iter(
        [_tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}), _final_response("added the dog food")]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        result = harness.handle_chat(db_session, "sess-upsell-4", "user_demo", "add dog food", 80_000, "req-1")

    assert result.upsell is None
    assert result.cart["total_paise"] == 74000  # the base add itself still succeeded

    trail = harness._audit.get_trail(db_session, "sess-upsell-4")
    blocked = [e for e in trail if e.event_type == "upsell_blocked"]
    assert len(blocked) == 1
    assert blocked[0].rule_name == "SpendCapRule"
    assert not any(e.event_type == "upsell_proposed" for e in trail)


def test_upsell_not_reoffered_after_session_cap_reached(db_session):
    """Default policy_upsell_max_per_session=1 — a second, unrelated add
    must not trigger a second offer."""
    seed_pet_pairing(db_session)
    product_repo.upsert(
        db_session,
        {
            "sku": "GRO-004",
            "name": "Tata Salt",
            "brand": "Tata",
            "category": "groceries",
            "price_paise": 2800,
            "unit": "1kg",
            "stock": 100,
            "description": "salt",
            "tags": [],
        },
    )
    db_session.commit()

    scripted_1 = iter([_tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}), _final_response("added")])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_1)):
        first = harness.handle_chat(db_session, "sess-upsell-5", "user_demo", "add dog food", 500_000, "req-1")
    assert first.upsell is not None

    scripted_2 = iter([_tool_call_response("add_to_cart", {"sku": "GRO-004", "quantity": 1}), _final_response("added salt too")])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_2)):
        second = harness.handle_chat(db_session, "sess-upsell-5", "user_demo", "add salt too", None, "req-2")

    # The first offer is still outstanding (never resolved) — no new one proposed.
    assert second.upsell is not None
    assert second.upsell["sku"] == "PET-004"
    trail = harness._audit.get_trail(db_session, "sess-upsell-5")
    assert sum(1 for e in trail if e.event_type == "upsell_proposed") == 1


def test_stale_upsell_offer_auto_declined_at_payment(db_session):
    seed_pet_pairing(db_session)
    scripted_1 = iter([_tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}), _final_response("added")])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_1)):
        first = harness.handle_chat(db_session, "sess-upsell-6", "user_demo", "add dog food", 500_000, "req-1")
    assert first.upsell is not None

    scripted_2 = iter([_tool_call_response("initiate_payment", {})])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_2)):
        proposal = harness.handle_chat(db_session, "sess-upsell-6", "user_demo", "pay now", None, "req-2")
    assert proposal.status == "awaiting_confirmation"
    # The offer is only resolved once the user actually goes through with
    # payment (confirms), not merely proposes it.
    assert proposal.upsell is not None

    scripted_3 = iter([_final_response("Order created, complete checkout.")])
    with (
        patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_3)),
        patch(
            "app.orders.service.gateway.create_order",
            return_value=RazorpayOrder(razorpay_order_id="order_upsell_1", amount_paise=74000, currency="INR", receipt="r"),
        ),
    ):
        confirmed = harness.handle_confirm(db_session, "sess-upsell-6", "user_demo", True, "req-3")

    assert confirmed.upsell is None

    trail = harness._audit.get_trail(db_session, "sess-upsell-6")
    declined = [e for e in trail if e.event_type == "upsell_declined"]
    assert len(declined) == 1
    assert declined[0].actor == "system"
    assert "proceeded to payment" in declined[0].reason
