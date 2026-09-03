"""Structured demand extraction — the one place in Layer 4.8 an LLM is used;
everything downstream (aggregation, thresholds, notifications — see
app/demand/aggregation.py) is deterministic Python. See docs/048-demand-loop.md.

Runs once per buyer chat turn (one call to harness.handle_chat, which can
span several internal tool-call iterations) — after the harness has finished
processing it, so the outcome is read back from what actually happened this
turn (the audit log), never guessed from chat text. Never blocks or fails
the chat turn itself: any extraction failure is logged and swallowed,
exactly like every other best-effort side channel in this project
(app/campaigns/service.py::log_product_view is the precedent).
"""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.core.logging import logger
from app.llm.gateway import GatewayError, gateway
from app.models.demand_signal import DemandSignal

_audit = AuditService()

_EXTRACTION_SYSTEM_PROMPT = (
    "You classify one shopper's chat message for a retail demand-tracking system. "
    "Reply with ONLY a JSON object, no prose, no markdown fences, matching exactly this shape: "
    '{"has_product_intent": bool, "category": string|null, "attributes": object}. '
    "has_product_intent is true only if the message expresses wanting to find, compare, or buy a "
    "specific kind of product (a size, a price ceiling, a dietary or quality constraint, a category "
    "ask) — false for greetings, thanks, questions about an order/cart/payment status, or anything "
    "with no product want in it. category is a short lowercase noun phrase for the kind of product "
    "(e.g. 'chocolate', 'dog food', 'rice'), or null if has_product_intent is false. attributes is a "
    "flat object of the specific constraints actually stated (e.g. {\"max_price_paise\": 5000, "
    "\"max_sugar_g\": 5, \"size\": \"50g\"}) — omit anything not actually said; use {} if none were."
)


def _strip_markdown_fence(content: str) -> str:
    """A common, cheap-to-handle failure mode: the model wraps otherwise-
    valid JSON in a ```json ... ``` fence despite being told not to."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]  # drop the opening ``` or ```json line
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _parse(content: str | None) -> dict | None:
    try:
        parsed = json.loads(_strip_markdown_fence(content or "{}"))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract(user_message: str) -> tuple[bool, str | None, dict]:
    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    parsed = None
    # Structured JSON output from an LLM is occasionally malformed (a
    # missing quote, a stray comma) even with an explicit "ONLY JSON"
    # instruction — observed live, not hypothetical (see Failures.md). One
    # retry on a fresh sample is cheap for a best-effort side channel and
    # meaningfully improves the real hit rate; a second failure is still
    # handled gracefully (returns "no intent detected", never raises).
    for attempt in range(2):
        try:
            result = gateway.call(messages, [])
        except GatewayError as e:
            logger.warning("demand signal extraction failed", extra={"error": str(e), "attempt": attempt + 1})
            return False, None, {}

        parsed = _parse(result.content)
        if parsed is not None:
            break
        logger.warning(
            "demand signal extraction returned non-JSON",
            extra={"content": (result.content or "")[:200], "attempt": attempt + 1},
        )

    if parsed is None:
        return False, None, {}

    has_intent = bool(parsed.get("has_product_intent"))
    category = parsed.get("category")
    attributes = parsed.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    return has_intent, (category if isinstance(category, str) and category.strip() else None), attributes


def _classify_turn_outcome(turn_events: list) -> tuple[str | None, str | None]:
    """Reads back what actually happened this turn from the audit log —
    never guessed from chat text. Only add_to_cart policy_decision events
    are relevant; the LAST one in the turn wins (a corrected retry that then
    succeeds should count as MATCHED, not an earlier DENY in the same turn).
    Returns (outcome, sku) where outcome is None if there's nothing to go
    on yet (no add attempted) or "SKIP" for a still-pending confirmation —
    resolved via a separate /api/agent/confirm call this module doesn't see,
    a documented simplification (see docs/048-demand-loop.md)."""
    add_decisions = [e for e in turn_events if e.event_type == "policy_decision" and e.tool_name == "add_to_cart"]
    if not add_decisions:
        return None, None
    last = add_decisions[-1]
    sku = (last.tool_args or {}).get("sku") if last.tool_args else None
    if last.decision == "ALLOW":
        return "MATCHED", sku
    if last.decision == "DENY":
        if last.rule_name in ("StockRule", "OutOfStockRule"):
            return "OUT_OF_STOCK", sku
        return "BLOCKED_BY_POLICY", sku
    return "SKIP", sku  # REQUIRE_CONFIRMATION


def maybe_capture(db: Session, session_id: str, user_message: str, turn_started_at: datetime) -> None:
    try:
        has_intent, category, attributes = _extract(user_message)
        if not has_intent:
            return

        events = _audit.get_trail(db, session_id)
        turn_events = [e for e in events if e.timestamp >= turn_started_at]
        outcome, matched_sku = _classify_turn_outcome(turn_events)
        if outcome == "SKIP":
            return
        if outcome is None:
            # The buyer wanted something and the agent never even attempted
            # an add — no product met the ask. This is Part 5's honest-
            # decline case, and it's read back from the log, not assumed:
            # the harness genuinely never proposed add_to_cart this turn.
            outcome = "NO_MATCH"

        db.add(
            DemandSignal(
                session_id=session_id,
                raw_query=user_message,
                category=category,
                extracted_attributes=attributes,
                # Populated whenever a real SKU was identified/attempted —
                # MATCHED, OUT_OF_STOCK, and BLOCKED_BY_POLICY all name one;
                # only a genuine NO_MATCH (no add_to_cart even attempted)
                # naturally has none, from _classify_turn_outcome above.
                matched_sku=matched_sku,
                outcome=outcome,
            )
        )
        db.commit()
    except Exception as e:  # never break the chat turn over telemetry
        db.rollback()
        logger.error("failed to capture demand signal", extra={"session_id": session_id, "error": str(e)})
