"""Resolves whoever is making this request into one typed Principal —
human or software — from whatever credential they presented. Two entirely
different trust mechanisms on purpose: a human's Authorization: Bearer JWT
proves "Google verified this person, and this backend then vouched for
them"; an agent's X-Agent-Key proves "this exact secret was issued to this
exact credential." Conflating the two into one token shape would blur a
distinction that matters — see docs/047-principals.md.

A revoked or over-scoped agent key still resolves successfully here (the
secret really was issued, it's genuinely this credential) — REJECTING it
is app/policy/rules.py's RevokedCredentialRule's job, not this module's,
so the denial is a normal, audited policy decision instead of a bare 401
with no trail.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi import Request
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token, hash_agent_key
from app.database import SessionLocal
from app.models.agent_credential import AgentCredential
from app.models.user import User

PrincipalType = Literal["buyer", "merchant", "agent", "pending"]


@dataclass(frozen=True)
class Principal:
    type: PrincipalType
    user_id: str  # the resource-owning buyer — for an agent, its credential's owner
    email: str | None = None  # humans only
    role: str | None = None  # "BUYER" | "MERCHANT" — humans only
    credential_id: str | None = None  # agents only
    credential_status: str | None = None  # agents only — "ACTIVE" | "REVOKED", read fresh every request
    scopes: frozenset[str] | None = None  # agents only
    spend_limit_paise: int | None = None  # agents only
    spent_paise: int | None = None  # agents only


def _resolve_from_jwt(token: str, db: Session) -> Principal | None:
    payload = decode_access_token(token)
    if payload is None:
        return None
    user = db.get(User, payload.get("sub"))
    if user is None:
        return None
    # Layer 4.8: a user with no role yet (hasn't been through /onboarding)
    # resolves to "pending" — a principal type no ordinary BUYER/MERCHANT-
    # gated endpoint accepts, so onboarding is a hard gate enforced by
    # SecureAPIRoute itself, not a client-side redirect a caller could skip.
    # See docs/048-demand-loop.md.
    ptype: PrincipalType = "pending" if user.role is None else ("merchant" if user.role == "MERCHANT" else "buyer")
    return Principal(type=ptype, user_id=user.id, email=user.email, role=user.role)


def _resolve_from_agent_key(raw_key: str, db: Session) -> Principal | None:
    key_hash = hash_agent_key(raw_key)
    cred = db.query(AgentCredential).filter(AgentCredential.key_hash == key_hash).first()
    if cred is None:
        return None
    cred.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return Principal(
        type="agent",
        user_id=cred.owner_user_id,
        credential_id=cred.id,
        credential_status=cred.status,
        scopes=frozenset(cred.scopes or []),
        spend_limit_paise=cred.spend_limit_paise,
        spent_paise=cred.spent_paise,
    )


def resolve_principal(request: Request) -> Principal | None:
    """Own short-lived DB session, separate from the request's own
    Depends(get_db) session — this runs inside the routing layer, before
    FastAPI's normal dependency injection has produced one."""
    agent_key = request.headers.get("x-agent-key")
    auth_header = request.headers.get("authorization")

    db = SessionLocal()
    try:
        if agent_key:
            return _resolve_from_agent_key(agent_key, db)
        if auth_header and auth_header.lower().startswith("bearer "):
            return _resolve_from_jwt(auth_header[7:].strip(), db)
        return None
    finally:
        db.close()
