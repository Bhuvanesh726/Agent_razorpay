from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.database import Base


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default=settings.default_user_id)

    # The budget the user explicitly stated for this session. Never inferred
    # from chat text — SpendCapRule reads only this column.
    budget_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # "active" | "awaiting_confirmation"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")

    # --- Layer 7: conversation history ---
    # Which agent credential this conversation belongs to. Sessions are owned
    # by user_id (a buyer), but a buyer can hold several agents, so user_id
    # alone cannot scope a history list to the agent currently selected in the
    # chat header. Nullable: sessions created before Layer 7, and any created
    # outside an agent principal, have none.
    credential_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Short label generated from the first user message (app/agent/titles.py).
    # Nullable — a conversation with no user turn yet has no title, and title
    # generation is allowed to fail without breaking the chat.
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Denormalised so the history list renders without counting rows per
    # conversation. Maintained in agent_session_repo.append_message.
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_active_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # The single tool call currently on hold pending user confirmation.
    # {"id": ..., "name": ..., "arguments": {...}}
    pending_tool_call: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pending_rule_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    pending_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="AgentMessage.seq"
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.session_id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    # "system" | "user" | "assistant" | "tool"
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Raw proposed tool calls, present on assistant messages that propose them.
    tool_calls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Present on tool-result messages.
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(60), nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)

    session: Mapped["AgentSession"] = relationship(back_populates="messages")
