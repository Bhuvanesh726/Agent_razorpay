"""The currently-authenticated Principal, visible deep inside the harness
and every tool without threading a parameter through every function
signature — same contextvar pattern app/testing/chaos.py already uses for
X-Chaos-Fault, and for the identical reason: audit logging happens from
dozens of call sites across harness.py, tools.py, and campaigns/service.py,
and routing every one of them through an explicit `principal` parameter
would touch far more of Layers 0-4.6's working code than this layer's own
regression-risk warning calls for. Set once, in app/auth/routing.py's
SecureAPIRoute wrapper, right where request.state.principal is set — every
audit event AuditService.log_event() writes during that request picks it
up automatically unless a caller (e.g. app/auth/credentials_router.py's
"Run now", which authenticates as the owning BUYER but must audit as the
AGENT) explicitly overrides it for a scoped block.
"""

import contextvars

from app.auth.principal import Principal

_current_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar("current_principal", default=None)


def set_current_principal(value: Principal | None) -> contextvars.Token:
    return _current_principal.set(value)


def reset_current_principal(token: contextvars.Token) -> None:
    _current_principal.reset(token)


def get_current_principal() -> Principal | None:
    return _current_principal.get()
