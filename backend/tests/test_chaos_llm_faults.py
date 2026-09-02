"""LLM-side chaos faults, run through the real harness + real policy engine.
No LLM stubbing needed for MALFORMED/HALLUCINATE — chaos itself replaces the
model call inside the gateway, deterministically and without any network
access, so the harness sees exactly what a real malformed/hallucinating
model would produce.
"""

from unittest.mock import patch

from app.agent import harness
from app.llm.gateway import LLMGateway
from app.repositories import product_repo
from app.testing import chaos


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


def _chaos_dev():
    return patch("app.testing.chaos.settings.app_env", "development")


def test_slow_llm_exhausts_retries_and_fails_gracefully(db_session):
    """Both models 'time out' -> GatewayError -> the harness catches it and
    returns a clear message, cart untouched, with an audit entry — not a
    stack trace, not a silent hang."""
    seed_pedigree(db_session)
    fast_gateway = LLMGateway(
        primary_model_id="test-primary",
        fallback_model_id="test-fallback",
        api_key="test",
        timeout_seconds=1.0,
        max_retries=0,
        backoff_base_seconds=0.0,
        circuit_breaker_failure_threshold=99,  # don't let the breaker mask this test
        circuit_breaker_cooldown_seconds=30.0,
    )
    with _chaos_dev(), patch("app.testing.chaos.settings.chaos_fault", "SLOW_LLM"), patch(
        "app.agent.harness.gateway", fast_gateway
    ):
        result = harness.handle_chat(db_session, "sess-chaos-slow", "user_demo", "hello", None, "req-1")

    assert result.status == "completed"
    assert "couldn't reach the model" in result.reply.lower()
    assert result.cart["items"] == []

    trail = harness._audit.get_trail(db_session, "sess-chaos-slow")
    assert any(e.event_type == "model_call_failed" for e in trail)


def test_malformed_tool_call_is_caught_and_capped(db_session):
    """Every iteration gets a malformed tool call back; the harness feeds
    the parse error to the model and retries within the cap, then gives up
    cleanly (not silently) once the cap is hit."""
    seed_pedigree(db_session)
    with _chaos_dev(), patch("app.testing.chaos.settings.chaos_fault", "LLM_MALFORMED_TOOL_CALL"):
        result = harness.handle_chat(db_session, "sess-chaos-malformed", "user_demo", "add dog food", None, "req-1")

    assert result.status == "iteration_limit"
    assert "step limit" in result.reply.lower()

    trail = harness._audit.get_trail(db_session, "sess-chaos-malformed")
    malformed_events = [e for e in trail if e.event_type == "malformed_tool_call"]
    limit_events = [e for e in trail if e.event_type == "iteration_limit_hit"]
    assert len(malformed_events) >= 1
    assert len(limit_events) == 1


def test_hallucinated_sku_is_denied_every_time_and_capped(db_session):
    seed_pedigree(db_session)
    with _chaos_dev(), patch("app.testing.chaos.settings.chaos_fault", "HALLUCINATE_SKU"):
        result = harness.handle_chat(db_session, "sess-chaos-hallucinate", "user_demo", "add dog food", None, "req-1")

    assert result.status == "iteration_limit"
    assert result.cart["items"] == []  # never actually added

    trail = harness._audit.get_trail(db_session, "sess-chaos-hallucinate")
    denials = [e for e in trail if e.decision == "DENY" and e.rule_name == "UnknownSkuRule"]
    assert len(denials) >= 1
    assert all("CHAOS-FAKE-SKU-999" in (e.reason or "") for e in denials)
