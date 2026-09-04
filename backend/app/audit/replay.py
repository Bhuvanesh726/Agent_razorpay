"""Reconstructs a full session from the audit log alone — no other table is
read. If this can't reproduce what happened, the log itself is incomplete;
that's what forced adding `tool_result` to audit_events (see
app/models/audit_event.py) — `tool_args` alone only records what was *asked*
for, never what actually happened (e.g. the price a cart line was executed
at, which can differ from the current catalog price by the time anyone
looks).
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.models.audit_event import AuditEvent

_audit = AuditService()

# Tool results that carry a full cart snapshot — the last one of these in the
# trail *is* the session's final cart state.
_CART_SNAPSHOT_TOOLS = {"add_to_cart", "remove_from_cart", "view_cart"}


@dataclass
class SessionReplay:
    session_id: str
    events: list[AuditEvent]
    narrative: list[str]
    final_cart: dict | None
    final_order_status: str | None


def _describe(event: AuditEvent) -> str:
    parts = [f"[{event.actor}] {event.event_type}"]
    if event.tool_name:
        parts.append(f"tool={event.tool_name}")
    if event.event_type == "confirmation_approved" and event.tool_args:
        # Distinguishes an explicit chat confirmation from a product card's
        # one-click confirm-to-buy (app/agent/harness.py::quick_purchase) —
        # otherwise the two are indistinguishable in this narrative.
        source = event.tool_args.get("confirmation_source")
        if source:
            parts.append(f"via={source}")
    if event.decision:
        parts.append(f"decision={event.decision}")
    if event.rule_name:
        parts.append(f"rule={event.rule_name}")
    if event.reason:
        parts.append(f"— {event.reason}")
    return " ".join(parts)


def replay_session(db: Session, session_id: str) -> SessionReplay:
    events = _audit.get_trail(db, session_id)

    narrative: list[str] = []
    final_cart: dict | None = None
    final_order_status: str | None = None

    for event in events:
        narrative.append(_describe(event))

        if event.event_type != "tool_executed" or not event.tool_result:
            continue

        if event.tool_name in _CART_SNAPSHOT_TOOLS:
            # add_to_cart/remove_from_cart/view_cart all return the full
            # current cart, so the latest one is the session's final state.
            final_cart = event.tool_result
        elif event.tool_name == "initiate_payment" and "status" in event.tool_result:
            final_order_status = event.tool_result["status"]

    # A later payment_succeeded/payment_failed (outside the agent tool call —
    # those happen via the payments router, not a harness tool) supersedes
    # whatever initiate_payment last reported.
    for event in events:
        if event.event_type == "payment_succeeded":
            final_order_status = "PAID"
        elif event.event_type == "payment_failed":
            final_order_status = "FAILED"

    return SessionReplay(
        session_id=session_id,
        events=events,
        narrative=narrative,
        final_cart=final_cart,
        final_order_status=final_order_status,
    )
