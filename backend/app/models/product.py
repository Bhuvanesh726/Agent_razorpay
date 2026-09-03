from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (Index("ix_products_category", "category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    # Cost basis for MarginFloorRule (Layer 4.6) — never shown to a shopper,
    # only used to keep a campaign discount from selling below a floor margin.
    cost_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(60), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Layer 4.8: a merchant-set markdown, 0 < pct <= campaign_max_discount_pct
    # (the same cap the campaign system already enforces — see
    # app/routers/merchant.py). None = no discount. price_paise stays the
    # real list price always; app/services/product_service.py's
    # effective_price_paise() is the one place "what a buyer actually pays"
    # is computed from the two together.
    discount_pct: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Feed freshness signal for a consuming agent's ETag/Last-Modified cache
    # (Layer 4.5) — not used anywhere before the catalog feed.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Catalog isn't per-user yet, but every table carries user_id from day one
    # so Google OAuth (later layer) needs zero schema changes.
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default=settings.default_user_id)
