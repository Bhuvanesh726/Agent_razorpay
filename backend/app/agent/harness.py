"""The agent loop.

for iteration in range(MAX_ITERATIONS):
    response = llm_gateway.call(messages, tools)
    if no tool call: break and return text
    decision = policy_engine.evaluate(proposed_action, session_state)
    audit.log(proposed_action, decision)
    if DENY: feed the denial + reason back to the model as the tool result
    if REQUIRE_CONFIRMATION: halt, return a confirmation prompt to the user
    if ALLOW: execute the tool, append result, continue

The model proposes; it never executes. `_execute_tool` is the only place a
tool actually runs, and it is only ever reached after the policy engine has
said ALLOW (or the user has explicitly confirmed via /api/agent/confirm).
"""

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from app.audit.service import AuditService
from app.core.config import settings
from app.core.logging import logger
from app.llm.gateway import GatewayError, ToolCall as GatewayToolCall, gateway
from app.orders import repository as order_repo
from app.orders.idempotency import compute_idempotency_key
from app.policy.engine import default_policy_engine
from app.policy.types import CartLineSnapshot, CatalogProductSnapshot, Decision, ProposedCartState
from app.repositories import agent_session_repo, cart_repo, product_repo
from app.services import cart_service

SYSTEM_PROMPT = (
    "You are a shopping assistant for an online store. All prices are in Indian Rupees "
    "but every tool speaks in integer paise (100 paise = 1 rupee; e.g. ₹800 = 80000). "
    "Only reference products and prices that a tool result actually returned to you — "
    "never invent a SKU or a price. "
    "When the user expresses clear intent to get an item within some constraint (price, "
    "category, etc.) and search_products returns one clearly-best match for it, add it to "
    "the cart directly rather than just listing options and waiting to be asked — you don't "
    "need permission to propose an add, the policy engine will check it before anything "
    "actually happens. Ask first only when multiple options are genuinely equally good, or "
    "the request is ambiguous. "
    "If a tool result contains an 'error' field, the action did not happen: explain the "
    "reason to the user plainly and do not retry the same action with different arguments "
    "to try to get around it. Only one tool call is processed per turn. "
    "When the user wants to pay or check out, call initiate_payment — it always requires "
    "the user's explicit confirmation, so you don't need to ask permission before proposing it."
)

_audit = AuditService()
_policy = default_policy_engine()


@dataclass
class HarnessResult:
    reply: str
    status: str  # "completed" | "awaiting_confirmation" | "iteration_limit"
    pending: dict | None
    cart: dict
    # Populated only right after a successful initiate_payment execution —
    # what the frontend needs to open Razorpay Checkout. Never contains the
    # key secret (payment_gateway.public_key_id is the publishable id).
    payment: dict | None = None


def handle_chat(
    db: Session,
    session_id: str,
    user_id: str,
    user_message: str,
    budget_paise: int | None,
    request_id: str | None,
) -> HarnessResult:
    session = agent_session_repo.get_or_create_session(db, session_id, user_id, budget_paise)
    db.commit()

    if session.status == "awaiting_confirmation":
        return HarnessResult(
            reply="There's a pending action awaiting your confirmation before I can continue — "
            "call /api/agent/confirm to approve or decline it.",
            status="awaiting_confirmation",
            pending=_pending_dict(session),
            cart=_cart_dict(db, user_id),
        )

    agent_session_repo.append_message(db, session_id, "user", content=user_message)
    db.commit()
    _audit.log_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type="user_message",
        actor="user",
        reason=user_message,
        request_id=request_id,
    )

    return _run_loop(db, session, request_id)


def handle_confirm(
    db: Session, session_id: str, user_id: str, approve: bool, request_id: str | None
) -> HarnessResult:
    session = agent_session_repo.get_session(db, session_id)
    if session is None or session.status != "awaiting_confirmation" or not session.pending_tool_call:
        return HarnessResult(
            reply="There is nothing awaiting confirmation for this session.",
            status="completed",
            pending=None,
            cart=_cart_dict(db, user_id),
        )

    pending = session.pending_tool_call
    tool_name = pending["name"]
    arguments = pending["arguments"]
    tool_call_id = pending["id"]

    if not approve:
        _audit.log_event(
            db,
            session_id=session_id,
            user_id=user_id,
            event_type="confirmation_rejected",
            actor="user",
            tool_name=tool_name,
            tool_args=arguments,
            request_id=request_id,
        )
        agent_session_repo.append_message(
            db,
            session_id,
            "tool",
            content=json.dumps({"error": "The user declined to confirm this action."}),
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )
        agent_session_repo.clear_pending(db, session)
        db.commit()
        return _run_loop(db, session, request_id)

    _audit.log_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type="confirmation_approved",
        actor="user",
        tool_name=tool_name,
        tool_args=arguments,
        rule_name=session.pending_rule_name,
        reason=session.pending_reason,
        request_id=request_id,
    )

    result = _execute_tool(db, user_id, session_id, tool_name, arguments)
    agent_session_repo.append_message(
        db, session_id, "tool", content=json.dumps(result), tool_call_id=tool_call_id, tool_name=tool_name
    )
    _audit.log_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type="tool_executed",
        actor="agent",
        tool_name=tool_name,
        tool_args=arguments,
        decision="ALLOW",
        reason="Executed after explicit user confirmation.",
        request_id=request_id,
    )
    agent_session_repo.clear_pending(db, session)
    db.commit()

    payment_info = result if tool_name == "initiate_payment" and "error" not in result else None
    if payment_info is not None:
        # Payment needs a browser round-trip (Razorpay Checkout) before the
        # conversation can meaningfully continue — surface it immediately
        # rather than looping the model again.
        return HarnessResult(
            reply=f"Order created — ₹{payment_info['amount_paise'] / 100:.2f}. "
            "Complete the payment in the checkout popup.",
            status="completed",
            pending=None,
            cart=_cart_dict(db, user_id),
            payment=payment_info,
        )

    return _run_loop(db, session, request_id)


def _run_loop(db: Session, session, request_id: str | None) -> HarnessResult:
    session_id = session.session_id
    user_id = session.user_id

    for _ in range(settings.agent_max_iterations):
        messages = _build_messages(db, session_id)

        try:
            gw_result = gateway.call(messages, TOOL_SCHEMAS)
        except GatewayError as e:
            logger.error("both primary and fallback model calls failed", extra={"session_id": session_id, "error": str(e)})
            _audit.log_event(
                db,
                session_id=session_id,
                user_id=user_id,
                event_type="model_call_failed",
                actor="system",
                reason=str(e),
                request_id=request_id,
            )
            return HarnessResult(
                reply="I couldn't reach the model right now (both primary and fallback failed). Please try again shortly.",
                status="completed",
                pending=None,
                cart=_cart_dict(db, user_id),
            )

        _audit.log_event(
            db,
            session_id=session_id,
            user_id=user_id,
            event_type="model_call",
            actor="agent",
            model_used=gw_result.model_used,
            latency_ms=gw_result.latency_ms,
            reason=f"fallback_used={gw_result.fallback_used}",
            request_id=request_id,
            prompt_tokens=gw_result.prompt_tokens,
            completion_tokens=gw_result.completion_tokens,
            total_tokens=gw_result.total_tokens,
            cost_paise=gw_result.cost_paise,
            fallback_used=gw_result.fallback_used,
        )

        if not gw_result.tool_calls:
            agent_session_repo.append_message(db, session_id, "assistant", content=gw_result.content or "")
            _audit.log_event(
                db,
                session_id=session_id,
                user_id=user_id,
                event_type="final_response",
                actor="agent",
                model_used=gw_result.model_used,
                request_id=request_id,
            )
            db.commit()
            return HarnessResult(reply=gw_result.content or "", status="completed", pending=None, cart=_cart_dict(db, user_id))

        raw_tool_calls = [
            {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments_raw}}
            for tc in gw_result.tool_calls
        ]
        agent_session_repo.append_message(db, session_id, "assistant", content=gw_result.content, tool_calls=raw_tool_calls)
        db.commit()

        # Only the first proposed call is evaluated/executed this turn — keeps
        # policy gating unambiguous. Any others are acknowledged as skipped so
        # every tool_call_id in this turn has a matching result (required by
        # the API), and reconsidered by the model on its next turn if still needed.
        primary, *rest = gw_result.tool_calls
        for extra in rest:
            agent_session_repo.append_message(
                db,
                session_id,
                "tool",
                content=json.dumps({"skipped": "Only one tool call is processed per turn."}),
                tool_call_id=extra.id,
                tool_name=extra.name,
            )
        if rest:
            db.commit()

        outcome = _handle_tool_call(db, session, primary, request_id)
        if outcome is not None:
            return outcome

    _audit.log_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type="iteration_limit_hit",
        actor="system",
        reason=f"Stopped after {settings.agent_max_iterations} iterations without a final answer.",
        request_id=request_id,
    )
    return HarnessResult(
        reply="I've hit my step limit for this request without finishing. Please try rephrasing, "
        "or ask again to continue.",
        status="iteration_limit",
        pending=None,
        cart=_cart_dict(db, user_id),
    )


def _handle_tool_call(db: Session, session, tc: GatewayToolCall, request_id: str | None) -> HarnessResult | None:
    """Returns a HarnessResult if the loop must stop here (confirmation needed
    or a hard model-side failure), or None if the loop should continue."""
    session_id = session.session_id
    user_id = session.user_id

    _audit.log_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type="tool_call_proposed",
        actor="agent",
        tool_name=tc.name,
        tool_args={"raw": tc.arguments_raw},
        request_id=request_id,
    )

    if tc.name not in TOOL_FUNCTIONS:
        _respond_and_deny(
            db, session_id, user_id, tc, {"error": f"Unknown tool '{tc.name}'."}, event_type="unknown_tool",
            reason="Model proposed a tool that does not exist.", request_id=request_id,
        )
        return None

    args = _parse_tool_call(tc.name, tc.arguments_raw)
    if args is None:
        _respond_and_deny(
            db,
            session_id,
            user_id,
            tc,
            {"error": f"Malformed arguments for tool '{tc.name}'. Provide valid JSON matching the schema."},
            event_type="malformed_tool_call",
            reason="Could not parse or validate tool call arguments.",
            request_id=request_id,
        )
        return None

    action = _build_proposed_state(db, session, tc.name, args)
    decision_result = _policy.evaluate(action)
    _audit.log_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type="policy_decision",
        actor="policy",
        tool_name=tc.name,
        tool_args=args,
        decision=decision_result.decision.value,
        rule_name=decision_result.rule_name,
        reason=decision_result.reason,
        request_id=request_id,
    )

    if decision_result.decision == Decision.DENY:
        agent_session_repo.append_message(
            db,
            session_id,
            "tool",
            content=json.dumps({"error": decision_result.reason, "rule": decision_result.rule_name}),
            tool_call_id=tc.id,
            tool_name=tc.name,
        )
        db.commit()
        return None

    if decision_result.decision == Decision.REQUIRE_CONFIRMATION:
        agent_session_repo.set_pending(
            db,
            session,
            {"id": tc.id, "name": tc.name, "arguments": args},
            decision_result.rule_name,
            decision_result.reason,
        )
        db.commit()
        return HarnessResult(
            reply=decision_result.reason,
            status="awaiting_confirmation",
            pending=_pending_dict(session),
            cart=_cart_dict(db, user_id),
        )

    # ALLOW
    result = _execute_tool(db, user_id, session_id, tc.name, args)
    agent_session_repo.append_message(
        db, session_id, "tool", content=json.dumps(result), tool_call_id=tc.id, tool_name=tc.name
    )
    _audit.log_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type="tool_executed",
        actor="agent",
        tool_name=tc.name,
        tool_args=args,
        decision="ALLOW",
        request_id=request_id,
    )
    db.commit()
    return None


def _respond_and_deny(db, session_id, user_id, tc, error_payload, *, event_type, reason, request_id) -> None:
    agent_session_repo.append_message(
        db, session_id, "tool", content=json.dumps(error_payload), tool_call_id=tc.id, tool_name=tc.name
    )
    _audit.log_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type=event_type,
        actor="system",
        tool_name=tc.name,
        tool_args={"raw": tc.arguments_raw},
        decision="DENY",
        reason=reason,
        request_id=request_id,
    )
    db.commit()


def _build_messages(db: Session, session_id: str) -> list[dict]:
    stored = agent_session_repo.list_messages(db, session_id)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in stored:
        entry: dict = {"role": m.role}
        if m.content is not None:
            entry["content"] = m.content
        if m.tool_calls:
            entry["tool_calls"] = m.tool_calls
        if m.tool_call_id:
            entry["tool_call_id"] = m.tool_call_id
        if m.tool_name:
            entry["name"] = m.tool_name
        messages.append(entry)
    return messages


def _parse_tool_call(tool_name: str, arguments_raw: str) -> dict | None:
    try:
        parsed = json.loads(arguments_raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None

    try:
        if tool_name == "search_products":
            return {
                "query": str(parsed.get("query", "")),
                "max_price_paise": _coerce_positive_int(parsed.get("max_price_paise")),
                "category": (parsed.get("category") or None),
            }
        if tool_name in ("get_product", "remove_from_cart"):
            sku = parsed.get("sku")
            if not isinstance(sku, str) or not sku.strip():
                return None
            return {"sku": sku.strip()}
        if tool_name == "add_to_cart":
            sku = parsed.get("sku")
            if not isinstance(sku, str) or not sku.strip():
                return None
            quantity = int(parsed.get("quantity", 1))
            if quantity < 1:
                return None
            return {"sku": sku.strip(), "quantity": quantity}
        if tool_name in ("view_cart", "initiate_payment"):
            return {}
    except (TypeError, ValueError):
        return None
    return None


def _coerce_positive_int(value) -> int | None:
    if value is None:
        return None
    coerced = int(value)
    return coerced if coerced >= 0 else None


def _build_proposed_state(db: Session, session, tool_name: str, args: dict) -> ProposedCartState:
    cart = cart_repo.get_or_create_active_cart(db, session.user_id)
    current_total = sum(item.unit_price_paise * item.quantity for item in cart.items)

    if tool_name == "initiate_payment":
        # Price uses the cart's snapshot (what will actually be charged —
        # never re-priced from the live catalog). Stock uses the live
        # catalog (a genuine fulfillment constraint that can change).
        cart_line_items = tuple(
            CartLineSnapshot(
                product=CatalogProductSnapshot(
                    sku=item.product.sku, price_paise=item.unit_price_paise, stock=item.product.stock
                ),
                quantity=item.quantity,
            )
            for item in cart.items
        )
        return ProposedCartState(
            session_id=session.session_id,
            user_id=session.user_id,
            tool_name=tool_name,
            budget_paise=session.budget_paise,
            current_cart_total_paise=current_total,
            cart_line_items=cart_line_items,
            existing_order_status=_existing_order_status(session.user_id, cart, db),
        )

    sku = args.get("sku")
    quantity = args.get("quantity")
    product_snapshot = None
    if sku:
        product = product_repo.get_by_sku(db, sku)
        if product is not None:
            product_snapshot = CatalogProductSnapshot(sku=product.sku, price_paise=product.price_paise, stock=product.stock)

    return ProposedCartState(
        session_id=session.session_id,
        user_id=session.user_id,
        tool_name=tool_name,
        budget_paise=session.budget_paise,
        current_cart_total_paise=current_total,
        sku=sku,
        quantity=quantity,
        product=product_snapshot,
    )


def _existing_order_status(user_id: str, cart, db: Session) -> str | None:
    """Read-only lookup — computes the same idempotency key
    order_service.create_or_get_order would, but never creates anything.
    Policy evaluation must have zero side effects."""
    if not cart.items:
        return None
    line_items = [(item.product.sku, item.quantity, item.unit_price_paise) for item in cart.items]
    amount_paise = sum(qty * price for _, qty, price in line_items)
    key = compute_idempotency_key(user_id, line_items, amount_paise)
    existing = order_repo.find_by_idempotency_key(db, key)
    return existing.status if existing is not None else None


def _execute_tool(db: Session, user_id: str, session_id: str, tool_name: str, args: dict) -> dict:
    try:
        return TOOL_FUNCTIONS[tool_name](db, user_id, session_id, **args)
    except Exception as e:  # a tool must never crash the harness
        logger.error("tool execution failed", extra={"tool_name": tool_name, "error": str(e)})
        db.rollback()
        return {"error": f"Tool '{tool_name}' failed to execute: {e}"}


def _pending_dict(session) -> dict:
    pending = session.pending_tool_call or {}
    return {
        "tool_name": pending.get("name"),
        "arguments": pending.get("arguments"),
        "rule_name": session.pending_rule_name,
        "reason": session.pending_reason,
    }


def _cart_dict(db: Session, user_id: str) -> dict:
    return cart_service.get_cart(db, user_id).model_dump(mode="json")
