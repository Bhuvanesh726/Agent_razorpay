from datetime import datetime, timezone

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
        session = AgentSession(
            session_id=session_id,
            user_id=user_id,
            budget_paise=budget_paise,
            credential_id=_acting_credential_id(),
        )
        db.add(session)
        db.flush()
    else:
        if budget_paise is not None:
            session.budget_paise = budget_paise
        # Backfill for sessions that predate Layer 7's credential_id column,
        # so existing conversations appear in the history list of the agent
        # that is actually driving them rather than vanishing.
        if session.credential_id is None:
            session.credential_id = _acting_credential_id()
    return session


def _acting_credential_id() -> str | None:
    """The credential of the principal on this request, when it is an agent.

    Read from the contextvar rather than threaded through every caller — the
    same reason app/auth/context.py exists at all. A human buyer driving the
    chat directly has no credential and gets None.
    """
    from app.auth.context import get_current_principal

    principal = get_current_principal()
    if principal is None or principal.type != "agent":
        return None
    return principal.credential_id


def list_conversations(
    db: Session,
    *,
    user_id: str,
    credential_id: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
) -> list[AgentSession]:
    """History list, most recently active first.

    Always filtered by user_id: a conversation belongs to a buyer, and
    credential_id alone would let a revoked-then-reissued credential id surface
    someone else's history. credential_id narrows it further to one agent,
    which is how the chat header's history button scopes the list.

    Sessions with no messages are excluded — an id minted by opening the chat
    and never typing is not a conversation, and would otherwise fill the list
    with blank rows.
    """
    stmt = (
        select(AgentSession)
        .where(AgentSession.user_id == user_id, AgentSession.message_count > 0)
        .order_by(
            func.coalesce(AgentSession.last_active_at, AgentSession.updated_at).desc()
        )
        .limit(limit)
    )
    if credential_id is not None:
        stmt = stmt.where(AgentSession.credential_id == credential_id)
    if not include_archived:
        stmt = stmt.where(AgentSession.archived.is_(False))
    return list(db.scalars(stmt))


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

    # Denormalised counters, maintained here so the history list never has to
    # aggregate messages per conversation to render a row.
    session = get_session(db, session_id)
    if session is not None:
        session.message_count = (session.message_count or 0) + 1
        session.last_active_at = datetime.now(timezone.utc)

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
