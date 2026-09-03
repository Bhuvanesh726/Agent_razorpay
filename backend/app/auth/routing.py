"""Default-deny, enforced structurally rather than by convention.

The obvious way to add auth to a FastAPI app — sprinkle Depends(get_principal)
onto the endpoints that need it — fails open: an endpoint a developer forgot
to annotate is simply unauthenticated, silently. That is the opposite of
what this layer requires ("an endpoint with no declared auth requirement
must fail closed"), so the check has to live somewhere a missing annotation
can't skip it: in the route class itself, wrapping every handler before it
ever runs, refusing outright unless a marker says otherwise.

Usage: pass route_class=SecureAPIRoute to every APIRouter(...) in this
project, then mark every endpoint with exactly one of:

    @public                                  # e.g. /health, the catalog feed
    @requires(AuthRequirement.BUYER)
    @requires(AuthRequirement.BUYER, AuthRequirement.AGENT)   # either is fine
    @requires(AuthRequirement.MERCHANT)

An endpoint with neither decorator raises 403 for every caller, always —
proven by test_endpoint_with_no_auth_marker_fails_closed, which registers a
deliberately unmarked route and asserts it is unreachable.
"""

from collections.abc import Callable
from enum import Enum

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

from app.auth.context import reset_current_principal, set_current_principal
from app.auth.principal import resolve_principal

_MARKER = "__auth_requirement__"


class AuthRequirement(str, Enum):
    PUBLIC = "public"
    BUYER = "buyer"
    MERCHANT = "merchant"
    AGENT = "agent"
    # Layer 4.8: a signed-in human who hasn't picked buyer/merchant yet at
    # /onboarding. Only the onboarding endpoint and /api/auth/me accept it —
    # every ordinary BUYER/MERCHANT-gated endpoint rejects it by omission,
    # same default-deny mechanism as everything else in this file.
    PENDING = "pending"


def public(fn: Callable) -> Callable:
    setattr(fn, _MARKER, frozenset({AuthRequirement.PUBLIC}))
    return fn


def requires(*allowed: AuthRequirement) -> Callable[[Callable], Callable]:
    if not allowed:
        raise ValueError("requires(...) needs at least one AuthRequirement")

    def decorator(fn: Callable) -> Callable:
        setattr(fn, _MARKER, frozenset(allowed))
        return fn

    return decorator


class SecureAPIRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_handler = super().get_route_handler()
        requirement = getattr(self.endpoint, _MARKER, None)

        async def custom_handler(request: Request) -> Response:
            if requirement is None:
                raise HTTPException(
                    status_code=403,
                    detail="This endpoint declares no auth requirement and is denied by default. "
                    "Add @public or @requires(...) from app.auth.routing.",
                )
            if AuthRequirement.PUBLIC not in requirement:
                principal = resolve_principal(request)
                if principal is None:
                    raise HTTPException(status_code=401, detail="Authentication required.")
                if AuthRequirement(principal.type) not in requirement:
                    raise HTTPException(status_code=403, detail="Not authorized for this endpoint.")
                request.state.principal = principal
                token = set_current_principal(principal)
                try:
                    return await original_handler(request)
                finally:
                    reset_current_principal(token)
            return await original_handler(request)

        return custom_handler
