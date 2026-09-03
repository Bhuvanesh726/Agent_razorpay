from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditEvent(Base):
    """Append-only. No update/delete methods exist anywhere in the codebase
    for this table — see app/audit/repository.py, which only ever INSERTs."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)

    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # "user" | "agent" | "policy" | "system"
    actor: Mapped[str] = mapped_column(String(20), nullable=False)

    tool_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tool_args: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The tool's actual return value, populated on "tool_executed" events.
    # Without this, replay can only know what was *asked* for, never what
    # actually happened — e.g. add_to_cart's args say a sku+quantity, but
    # reconstructing the resulting cart total needs the price it was
    # executed at, which only the result (not the args) carries.
    tool_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # "ALLOW" | "DENY" | "REQUIRE_CONFIRMATION" | null
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    rule_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    model_used: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Populated on "model_call" events only, straight from the OpenAI-compatible
    # response's `usage` object (via the LLM gateway). cost_paise = total_tokens
    # * a configured per-token rate (0 by default — NVIDIA's current tier is free).
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Recorded at write time rather than re-derived from current config later,
    # so a config change never reinterprets historical audit rows.
    fallback_used: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Layer 4.7: who/what actually authorized this event, distinct from
    # `actor` (which step of the harness produced it — "agent"/"policy"/
    # "system"/"user") and distinct from `user_id` (whose data this is —
    # for an agent's action, the OWNING buyer, unchanged). "buyer" |
    # "merchant" | "agent" | null (events from before this layer, or system
    # events with no single responsible principal). principal_id is the
    # User.id for a human or the AgentCredential.id for an agent — so "agent
    # X acting for buyer Y" is principal_type="agent", principal_id=X,
    # user_id=Y, all on the same row.
    principal_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
