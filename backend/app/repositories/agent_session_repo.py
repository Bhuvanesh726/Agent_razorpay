from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent_session import AgentMessage, AgentSession


def get_session(db: Session, session_id: str) -> AgentSession | None:
    return db.scalar(select(AgentSession).where(AgentSession.session_id == session_id))


def list_recent_sessions(db: Session, *, limit: int = 25) -> list[AgentSession]:
    """Most-recently-active sessions first — backs the merchant audit
    viewer's session picker (app/routers/audit.py), so a merchant can find a
    session to inspect without a buyer having to hand them a session_id."""
    stmt = select(AgentSession).order_by(AgentSession.updated_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def get_or_create_session(
    db: Session, session_id: str, user_id: str, budget_paise: int | None
) -> AgentSession:
    session = get_session(db, session_id)
    if session is None:
        session = AgentSession(session_id=session_id, user_id=user_id, budget_paise=budget_paise)
        db.add(session)
        db.flush()
    elif budget_paise is not None:
        session.budget_paise = budget_paise
    return session


def list_messages(db: Session, session_id: str) -> list[AgentMessage]:
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.seq)
    )
    return list(db.scalars(stmt))


def append_message(
    db: Session,
    session_id: str,
    role: str,
    *,
    content: str | None = None,
    tool_calls: list | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
) -> AgentMessage:
    next_seq = db.scalar(
        select(func.coalesce(func.max(AgentMessage.seq), 0)).where(AgentMessage.session_id == session_id)
    )
    message = AgentMessage(
        session_id=session_id,
        seq=(next_seq or 0) + 1,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
    )
    db.add(message)
    db.flush()
    return message


def set_pending(db: Session, session: AgentSession, tool_call: dict, rule_name: str, reason: str) -> None:
    session.status = "awaiting_confirmation"
    session.pending_tool_call = tool_call
    session.pending_rule_name = rule_name
    session.pending_reason = reason
    db.flush()


def clear_pending(db: Session, session: AgentSession) -> None:
    session.status = "active"
    session.pending_tool_call = None
    session.pending_rule_name = None
    session.pending_reason = None
    db.flush()
