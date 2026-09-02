"""Deliberate fault injection for demoing graceful failure handling.

OFF by default. The safety gate is `_chaos_available()`: chaos only ever
activates when `APP_ENV=development`. No env var, no header, nothing else can
turn it on — there is no path to enabling this in a production config, by
construction, not by convention.

Two ways to trigger a fault, checked in this order:
1. A per-request header: `X-Chaos-Fault: SLOW_LLM` — affects only that one
   request. Read by `ChaosHeaderMiddleware` into a contextvar, so it's
   visible deep inside the gateway/service layers without threading a
   parameter through every function signature (same pattern as `request_id`
   in app/core/logging.py).
2. A global env var: `CHAOS_FAULT=SLOW_LLM` — sticky for the whole process,
   useful for a sustained demo segment without needing a header on every call.

Every injection point calls `log_injection(...)` right before doing its fault
behavior, so the audit trail always explains *why* something failed — a
demo/judge should never have to take "trust me, I broke it" on faith.
"""

import contextvars
from enum import Enum

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings
from app.core.logging import logger

CHAOS_HEADER = "X-Chaos-Fault"


class ChaosFault(str, Enum):
    FAIL_PAYMENT = "FAIL_PAYMENT"
    SLOW_LLM = "SLOW_LLM"
    LLM_MALFORMED_TOOL_CALL = "LLM_MALFORMED_TOOL_CALL"
    HALLUCINATE_SKU = "HALLUCINATE_SKU"
    RAZORPAY_TIMEOUT = "RAZORPAY_TIMEOUT"
    DB_CONFLICT = "DB_CONFLICT"
    TAMPERED_SIGNATURE = "TAMPERED_SIGNATURE"


_request_fault: contextvars.ContextVar[str | None] = contextvars.ContextVar("chaos_fault", default=None)


def _chaos_available() -> bool:
    return settings.app_env == "development"


def set_request_fault(value: str | None) -> contextvars.Token:
    return _request_fault.set(value)


def reset_request_fault(token: contextvars.Token) -> None:
    _request_fault.reset(token)


def active_fault() -> ChaosFault | None:
    """The per-request header takes precedence over the sticky env var."""
    if not _chaos_available():
        return None
    raw = _request_fault.get() or (settings.chaos_fault or None)
    if not raw:
        return None
    try:
        return ChaosFault(raw)
    except ValueError:
        logger.warning("unknown chaos fault requested", extra={"fault": raw})
        return None


def is_active(fault: ChaosFault) -> bool:
    return active_fault() == fault


class ChaosHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = set_request_fault(request.headers.get(CHAOS_HEADER))
        try:
            return await call_next(request)
        finally:
            reset_request_fault(token)


def log_injection(db, *, session_id: str, user_id: str, fault: ChaosFault, detail: str, request_id: str | None = None):
    """Import kept local to avoid a circular import (audit -> ... -> chaos
    is not needed anywhere else, but chaos is imported very widely)."""
    from app.audit.service import AuditService

    AuditService().log_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type="chaos_fault_injected",
        actor="system",
        reason=f"[{fault.value}] {detail}",
        request_id=request_id,
    )
