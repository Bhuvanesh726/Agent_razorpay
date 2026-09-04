"""Short conversation titles, generated from the buyer's first message.

Two properties this module is built around:

1. **A failed title must never break the chat.** Titling is cosmetic; the
   conversation is not. Every failure path — a model error, a timeout, an empty
   or nonsense completion — falls back to a truncation of the user's own
   message. `generate_title` does not raise.

2. **The title is untrusted text.** It is derived from user input and, worse,
   passed through a model that was asked to rewrite that input — so it can
   contain anything, including text shaped like an instruction. It is stored
   and rendered as data: capped in length here (the column is VARCHAR(120)),
   stripped of control characters and newlines, and never fed back into a
   prompt. React escapes it on render.
"""

import re

from app.core.logging import logger
from app.llm.gateway import GatewayError, gateway

# Comfortably under the VARCHAR(120) column, and short enough that a list of
# these stays scannable.
MAX_TITLE_CHARS = 60

_PROMPT = (
    "Write a short title for a shopping conversation that opens with the message below. "
    "Six words maximum. Describe what the shopper wants. "
    "Reply with the title only — no quotes, no punctuation at the end, no preamble.\n\n"
    "Message: {message}"
)

# Strip control characters (including newlines) rather than merely trimming:
# a title is a single-line label, and embedded newlines would let it forge
# extra rows in any plain-text rendering of the history list.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _clean(text: str) -> str:
    text = _CONTROL_CHARS.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Models like to wrap titles in quotes despite being told not to.
    text = text.strip("\"'“”‘’").strip()
    if len(text) > MAX_TITLE_CHARS:
        text = text[: MAX_TITLE_CHARS - 1].rstrip() + "…"
    return text


def fallback_title(user_message: str) -> str:
    """A truncation of the user's own message. Used when the model is
    unavailable, and as the floor under every other failure."""
    cleaned = _clean(user_message)
    return cleaned or "New conversation"


def generate_title(user_message: str) -> str:
    """One cheap model call, best-effort. Never raises."""
    fallback = fallback_title(user_message)

    try:
        result = gateway.call(
            [{"role": "user", "content": _PROMPT.format(message=user_message[:500])}],
            [],
        )
    except GatewayError as e:
        # Expected often enough not to be an error: the upstream provider is
        # flaky (see Failures.md), and a missing title costs the user nothing.
        logger.info("title generation unavailable, using fallback", extra={"error": str(e)})
        return fallback
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(
            "title generation raised unexpectedly, using fallback",
            extra={"error": str(e), "error_type": type(e).__name__},
        )
        return fallback

    title = _clean(result.content or "")
    if not title:
        return fallback
    return title


# Set to False by the test suite. Tests script the model with an iterator of
# responses (`patch("app.agent.harness.gateway.call", side_effect=...)`) and
# assert on that exact sequence; a title call landing on the same singleton
# from another thread would consume one nondeterministically. Production
# always leaves this on — tests that exercise titling call generate_title()
# directly instead.
BACKGROUND_TITLES_ENABLED = True


def schedule_title_generation(session_id: str) -> None:
    """Upgrade a conversation's fallback title to a generated one, off the
    request path.

    The caller has already stored `fallback_title(...)`, so the conversation
    is never untitled and this is purely an improvement. It runs in a daemon
    thread with its own database session — the request's session belongs to
    the request and is not safe to use from another thread — and swallows
    every failure: a title is worth no part of a chat turn's reliability.
    """
    if not BACKGROUND_TITLES_ENABLED:
        return

    import threading

    threading.Thread(target=_generate_and_store, args=(session_id,), daemon=True).start()


def _generate_and_store(session_id: str) -> None:
    from app.database import SessionLocal
    from app.repositories import agent_session_repo

    db = SessionLocal()
    try:
        session = agent_session_repo.get_session(db, session_id)
        if session is None:
            return
        first_user_message = next(
            (m.content for m in agent_session_repo.list_messages(db, session_id) if m.role == "user" and m.content),
            None,
        )
        if not first_user_message:
            return

        title = generate_title(first_user_message)
        # Re-read rather than trusting the row we loaded before a network
        # call: the buyer may have archived or renamed it meanwhile.
        session = agent_session_repo.get_session(db, session_id)
        if session is not None:
            session.title = title
            db.commit()
    except Exception as e:  # noqa: BLE001 - a background thread must never escape
        logger.warning(
            "background title generation failed",
            extra={"session_id": session_id, "error": str(e), "error_type": type(e).__name__},
        )
    finally:
        db.close()
