"""The output of app/demand/aggregation.py's threshold job — persisted (not
recomputed fresh every read) so a merchant's ACTED/DISMISSED decision on one
sticks, and so "close the loop" has an acted_at to measure subsequent
conversion against. See docs/048-demand-loop.md.

`evidence` is aggregate-only by construction (counts, categories, attributes,
SKUs) — never a raw_query or a session_id. The aggregation job that builds it
(app/demand/aggregation.py) only ever selects DemandSignal.category/
extracted_attributes/matched_sku/outcome in bulk, never raw_query; tested
directly in tests/test_demand_privacy.py.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MerchantNotification(Base):
    __tablename__ = "merchant_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # "UNMET_DEMAND" | "OUT_OF_STOCK_DEMAND" | "BROWSE_ABANDONMENT" | "ATTRIBUTE_GAP"
    type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # Stable per (type, category/sku) — how the aggregation job avoids ever
    # raising the same notification twice; see app/demand/aggregation.py.
    dedupe_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)

    # Counts and attributes only — see module docstring.
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    suggested_action: Mapped[str] = mapped_column(String(255), nullable=False)

    # "NEW" | "ACTED" | "DISMISSED"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="NEW")
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
