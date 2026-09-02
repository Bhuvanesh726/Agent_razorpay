from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
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
