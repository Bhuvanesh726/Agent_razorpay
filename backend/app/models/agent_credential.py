"""The one credential table backing both delivery modes (see
docs/047-principals.md). Only key_hash is ever stored — the plaintext key
exists only in memory for the single request that creates it (EXTERNAL) or
never leaves the server at all (EMBEDDED, which never returns it)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_credential_id() -> str:
    return f"agent_{uuid.uuid4().hex[:16]}"


class AgentCredential(Base):
    __tablename__ = "agent_credentials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_credential_id)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # "EMBEDDED" | "EXTERNAL" — see docs/047-principals.md. Same table, same
    # rules, same enforcement either way; this column only ever affects
    # whether an endpoint is willing to return the plaintext key once.
    delivery_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    # Tool names this credential may invoke — AgentScopeRule denies anything
    # not in this list. See settings.agent_available_scope_list for the
    # full set a buyer can choose from.
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    spend_limit_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    # Running total of ALLOWed spend under this credential, forever (not
    # per-window) — AgentSpendLimitRule denies once this would exceed the
    # limit, independent of whatever the session's own budget allows.
    spent_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # "ACTIVE" | "REVOKED"
    # Plain-language goal for "Run now" (embedded mode only) — fed to the
    # shopping harness as the user_message of one chat turn.
    standing_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
