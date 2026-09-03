"""Human principals. id is a string (not an autoincrement int) so it slots
into every existing user_id: str column (Cart, Order, AgentSession, ...)
with zero schema change to any of them — the seeded demo user's id is
literally "user_demo", the same literal every Layer 0-4.6 table already
uses, so nothing from those layers is orphaned by this layer. A real
Google-authenticated user gets id = f"google_{sub}" instead.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Nullable: the seeded demo user (id="user_demo") predates Google login
    # and never actually authenticated with Google.
    google_sub: Mapped[str | None] = mapped_column(String(120), unique=True, index=True, nullable=True)
    # "BUYER" | "MERCHANT" — see docs/047-principals.md for why these are
    # the only two roles a *human* gets (Agent is never a User row).
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="BUYER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
