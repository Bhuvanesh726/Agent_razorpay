"""One row per buyer chat turn where the agent's own conversation shows
product-seeking intent — see app/demand/capture.py for where these are
written and app/demand/aggregation.py for how they turn into merchant
notifications.

Deliberately has NO user_id / buyer-identifying column at all — "distinct
buyers" is approximated by distinct session_id (a session belongs to exactly
one buyer, one-to-one, via AgentSession). This isn't a convention that a
future query could accidentally violate; the identity simply isn't in the
table to select. See docs/048-demand-loop.md.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DemandSignal(Base):
    __tablename__ = "demand_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # The buyer's own message, verbatim. Retained for internal record-keeping
    # only — app/demand/aggregation.py's notification-building queries never
    # select this column into anything merchant-facing.
    raw_query: Mapped[str] = mapped_column(Text, nullable=False)

    category: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    # LLM-extracted constraints, e.g. {"max_price_paise": 500, "max_sugar_g": 5}
    # — shape is whatever the extraction prompt produced, not a fixed schema.
    extracted_attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    matched_sku: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # "MATCHED" | "NO_MATCH" | "OUT_OF_STOCK" | "BLOCKED_BY_POLICY"
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
