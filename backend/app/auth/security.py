"""Two unrelated kinds of secret handled here, on purpose kept in one small
module rather than two: this backend's own session JWTs (signs/verifies
what THIS server issues after Google has already verified the human) and
agent API keys (this server's own bearer secrets for software principals).
Neither has anything to do with Google's own tokens — those are verified,
once, in app/auth/oauth_router.py and never stored.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

AGENT_KEY_PREFIX = "agentkey_"


def generate_agent_key() -> str:
    """A fresh, high-entropy secret — never derived from anything (not the
    credential id, not the owner, nothing guessable)."""
    return f"{AGENT_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_agent_key(raw_key: str) -> str:
    """One-way. There is no un-hash — see AgentCredential.key_hash and
    docs/047-principals.md on why EMBEDDED mode's plaintext is truly gone
    the moment this function returns."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def create_access_token(*, sub: str, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
