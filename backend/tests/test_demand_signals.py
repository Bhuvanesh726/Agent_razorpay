"""Layer 4.8: demand-signal capture (app/demand/capture.py) and aggregation
(app/demand/aggregation.py). No live LLM — every gateway.call is scripted,
same pattern as tests/test_payment_flow_integration.py.
"""

import json
from unittest.mock import patch

import pytest

from app.agent import harness
from app.demand import aggregation
from app.llm.gateway import GatewayResult
from app.llm.gateway import ToolCall as GatewayToolCall
from app.models.agent_session import AgentSession
from app.models.demand_signal import DemandSignal
from app.models.merchant_notification import MerchantNotification
from app.models.user import User
from app.repositories import product_repo


def seed_pedigree(db, *, stock: int = 25):
    product_repo.upsert(
        db,
        {
            "sku": "PET-001",
            "name": "Pedigree Adult Dry Dog Food",
            "brand": "Pedigree",
            "category": "pet_supplies",
            "price_paise": 74000,
            "unit": "3kg pack",
            "stock": stock,
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


def _extraction_response(has_intent: bool, category: str | None, attributes: dict) -> GatewayResult:
    payload = {"has_product_intent": has_intent, "category": category, "attributes": attributes}
    return _final_response(json.dumps(payload))


# --- capture: constraint mismatch -> NO_MATCH, nothing added to cart -----


def test_constraint_agent_cannot_satisfy_logs_no_match_and_adds_nothing(db_session):
    seed_pedigree(db_session)
    scripted = iter(
        [
            _final_response("Sorry, I don't have any chocolate with 5g of sugar or less in stock."),
            _extraction_response(True, "chocolates", {"max_sugar_g": 5}),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        result = harness.handle_chat(
            db_session, "sess-no-match", "user_demo", "I need chocolate with under 5g of sugar", 100_000, "req-1"
        )

    assert result.status == "completed"
    assert result.cart["items"] == []

    signals = db_session.query(DemandSignal).filter_by(session_id="sess-no-match").all()
    assert len(signals) == 1
    assert signals[0].outcome == "NO_MATCH"
    assert signals[0].category == "chocolates"
    assert signals[0].extracted_attributes == {"max_sugar_g": 5}
    assert signals[0].matched_sku is None
    assert signals[0].raw_query == "I need chocolate with under 5g of sugar"


def test_malformed_json_on_first_extraction_attempt_retries_and_succeeds(db_session):
    """Observed live (see Failures.md): the model occasionally returns
    syntactically invalid JSON for the extraction prompt despite explicit
    instructions. One retry on a fresh sample should recover instead of
    silently dropping the signal."""
    seed_pedigree(db_session)
    malformed = GatewayResult(
        content='{"has_product_intent": true, "category": "chocolate,  "attributes": {}}',  # missing closing quote
        tool_calls=[],
        model_used="test-model",
        fallback_used=False,
        latency_ms=1,
    )
    scripted = iter(
        [
            _final_response("Sorry, nothing matches that."),
            malformed,
            _extraction_response(True, "chocolates", {"max_sugar_g": 5}),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        harness.handle_chat(db_session, "sess-retry-recovery", "user_demo", "chocolate under 5g sugar", 100_000, "req-1")

    signals = db_session.query(DemandSignal).filter_by(session_id="sess-retry-recovery").all()
    assert len(signals) == 1
    assert signals[0].outcome == "NO_MATCH"
    assert signals[0].category == "chocolates"


def test_markdown_fenced_json_is_still_parsed(db_session):
    seed_pedigree(db_session)
    fenced = GatewayResult(
        content='```json\n{"has_product_intent": true, "category": "rice", "attributes": {}}\n```',
        tool_calls=[],
        model_used="test-model",
        fallback_used=False,
        latency_ms=1,
    )
    scripted = iter([_final_response("Sorry, nothing matches that."), fenced])
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        harness.handle_chat(db_session, "sess-fenced", "user_demo", "rice under 500 paise", 100_000, "req-1")

    signals = db_session.query(DemandSignal).filter_by(session_id="sess-fenced").all()
    assert len(signals) == 1
    assert signals[0].category == "rice"


def test_no_product_intent_message_captures_nothing(db_session):
    seed_pedigree(db_session)
    scripted = iter(
        [
            _final_response("You're welcome!"),
            _extraction_response(False, None, {}),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        harness.handle_chat(db_session, "sess-chitchat", "user_demo", "thanks!", 100_000, "req-1")

    assert db_session.query(DemandSignal).filter_by(session_id="sess-chitchat").count() == 0


def test_successful_add_captures_matched_with_sku(db_session):
    seed_pedigree(db_session)
    scripted = iter(
        [
            _tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}),
            _final_response("Added the dog food to your cart."),
            _extraction_response(True, "dog food", {}),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        result = harness.handle_chat(db_session, "sess-matched", "user_demo", "add dog food", 100_000, "req-1")

    assert len(result.cart["items"]) == 1
    signals = db_session.query(DemandSignal).filter_by(session_id="sess-matched").all()
    assert len(signals) == 1
    assert signals[0].outcome == "MATCHED"
    assert signals[0].matched_sku == "PET-001"


def test_out_of_stock_attempt_captures_out_of_stock_outcome(db_session):
    seed_pedigree(db_session, stock=0)
    scripted = iter(
        [
            _tool_call_response("add_to_cart", {"sku": "PET-001", "quantity": 1}),
            _final_response("That's out of stock right now, sorry."),
            _extraction_response(True, "dog food", {}),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        result = harness.handle_chat(db_session, "sess-oos", "user_demo", "add dog food", 100_000, "req-1")

    assert result.cart["items"] == []
    signals = db_session.query(DemandSignal).filter_by(session_id="sess-oos").all()
    assert len(signals) == 1
    assert signals[0].outcome == "OUT_OF_STOCK"
    assert signals[0].matched_sku == "PET-001"


def test_extraction_failure_never_breaks_the_chat_turn(db_session):
    """The extraction call itself raising must not surface as an error to
    the buyer — capture.maybe_capture swallows it (see its docstring)."""
    seed_pedigree(db_session)

    def _raise_on_second_call(*a, **k):
        raise RuntimeError("simulated extraction failure")

    scripted = iter([_final_response("Sure, here's what I found.")])

    def side_effect(*a, **k):
        try:
            return next(scripted)
        except StopIteration:
            return _raise_on_second_call(*a, **k)

    with patch("app.agent.harness.gateway.call", side_effect=side_effect):
        result = harness.handle_chat(db_session, "sess-extract-fail", "user_demo", "hello", 100_000, "req-1")

    assert result.status == "completed"
    assert result.reply == "Sure, here's what I found."


# --- aggregation: threshold (percentage + floor) --------------------------


def _make_active_buyers(db, n: int) -> None:
    for i in range(n):
        user_id = f"buyer-{i}"
        db.add(User(id=user_id, email=f"{user_id}@example.test", name=user_id, role="BUYER"))
        db.add(AgentSession(session_id=f"sess-active-{i}", user_id=user_id))
    db.commit()


def _make_no_match_signals(db, category: str, n: int, *, offset: int = 0) -> None:
    for i in range(offset, offset + n):
        db.add(
            DemandSignal(
                session_id=f"sess-nomatch-{category}-{i}",
                raw_query=f"raw query {i} for {category}",
                category=category,
                extracted_attributes={},
                matched_sku=None,
                outcome="NO_MATCH",
            )
        )
    db.commit()


def test_crosses_threshold_respects_percentage():
    # 20% default pct, floor 5 — 20 active buyers -> required = max(5, 4) = 5
    assert aggregation.crosses_threshold(5, active_buyers=20) is True
    assert aggregation.crosses_threshold(4, active_buyers=20) is False


def test_crosses_threshold_respects_absolute_floor():
    # 100 active buyers * 20% = 20, but the floor (5) never applies here
    # since 20 > 5 — use a case where pct alone would demand FEWER than the
    # floor: 10 active buyers * 20% = 2 -> floor of 5 wins.
    assert aggregation.crosses_threshold(4, active_buyers=10) is False
    assert aggregation.crosses_threshold(5, active_buyers=10) is True


def test_unmet_demand_notification_raised_only_once_threshold_crossed(db_session):
    _make_active_buyers(db_session, 20)  # required = max(5, 20*0.2) = 5
    _make_no_match_signals(db_session, "chocolates", 4)

    aggregation.run(db_session)
    assert db_session.query(MerchantNotification).filter_by(type="UNMET_DEMAND").count() == 0

    _make_no_match_signals(db_session, "chocolates", 1, offset=4)  # now 5 distinct sessions
    aggregation.run(db_session)
    notifications = db_session.query(MerchantNotification).filter_by(type="UNMET_DEMAND").all()
    assert len(notifications) == 1
    assert notifications[0].evidence["category"] == "chocolates"
    assert notifications[0].evidence["distinct_buyers"] == 5


def test_aggregation_is_idempotent_never_duplicates_a_notification(db_session):
    _make_active_buyers(db_session, 20)
    _make_no_match_signals(db_session, "chocolates", 5)

    aggregation.run(db_session)
    aggregation.run(db_session)
    aggregation.run(db_session)

    assert db_session.query(MerchantNotification).filter_by(type="UNMET_DEMAND").count() == 1


# --- privacy: notifications never carry buyer identity or raw queries -----


def test_notification_evidence_never_contains_raw_query_or_session_id(db_session):
    _make_active_buyers(db_session, 20)
    secret_query = "MY SECRET RAW QUERY TEXT THAT MUST NEVER LEAK"
    for i in range(5):
        db_session.add(
            DemandSignal(
                session_id=f"sess-privacy-{i}",
                raw_query=secret_query,
                category="chocolates",
                extracted_attributes={"max_sugar_g": 5},
                matched_sku=None,
                outcome="NO_MATCH",
            )
        )
    db_session.commit()

    aggregation.run(db_session)

    notifications = db_session.query(MerchantNotification).all()
    assert len(notifications) >= 1
    for n in notifications:
        blob = json.dumps({"evidence": n.evidence, "suggested_action": n.suggested_action, "dedupe_key": n.dedupe_key})
        assert secret_query not in blob
        for i in range(5):
            assert f"sess-privacy-{i}" not in blob


def test_merchant_notification_model_has_no_user_identifying_columns():
    """Structural, not conventional: DemandSignal has no user_id/buyer
    identity column at all, so a query can't select what isn't there."""
    columns = {c.name for c in DemandSignal.__table__.columns}
    assert "user_id" not in columns
    assert "buyer_id" not in columns
