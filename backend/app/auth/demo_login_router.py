"""Development-only sign-in as a pre-seeded buyer or merchant.

Exists so a reviewer can open the app without first registering a Google
Cloud OAuth client — the one genuinely external dependency in the sign-in
path. Production posture is unchanged: app/auth/oauth_router.py remains the
only way a human authenticates, because the POST below 404s outside
APP_ENV=development.

The gate is app/testing/demo_login.py::demo_login_available(), the same
construction that gates chaos injection — a property of the environment, not
a config flag someone could flip by accident. See tests/test_demo_login_gate.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.auth.routing import SecureAPIRoute, public
from app.auth.security import create_access_token
from app.core.logging import logger
from app.database import get_db
from app.models.user import User
from app.schemas.demo_login import DemoLoginOptions, DemoLoginRequest, DemoLoginResult, DemoPrincipalOut
from app.testing.demo_login import demo_login_available, demo_principals, ensure_demo_environment

router = APIRouter(tags=["auth"], route_class=SecureAPIRoute)
_audit = AuditService()

_DESCRIPTIONS = {
    "BUYER": "Signs in with an agent credential, two past orders and browsing history already in place.",
    "MERCHANT": "Sees the merchant dashboards, order list, campaigns and audit trail.",
}


@router.get("/api/auth/demo-login", response_model=DemoLoginOptions)
@public
def demo_login_options() -> DemoLoginOptions:
    """Lets the sign-in page decide whether to offer the demo buttons.
    Returns available=false rather than 404 outside development: this is a
    UI hint, and the POST is where the gate is actually enforced."""
    if not demo_login_available():
        return DemoLoginOptions(available=False, principals=[])
    return DemoLoginOptions(
        available=True,
        principals=[
            DemoPrincipalOut(
                role=p.role,
                email=p.email,
                name=p.name,
                description=_DESCRIPTIONS[p.role],
            )
            for p in demo_principals().values()
        ],
    )


@router.post("/api/auth/demo-login", response_model=DemoLoginResult)
@public
def demo_login(
    payload: DemoLoginRequest, request: Request, db: Session = Depends(get_db)
) -> DemoLoginResult:
    if not demo_login_available():
        # 404, not 403: outside development this endpoint is indistinguishable
        # from one that was never deployed. Same response the other dev-only
        # endpoints give (app/auth/role_router.py::switch_role,
        # app/routers/payments.py::test_complete).
        raise HTTPException(status_code=404, detail="Not found.")

    principal = demo_principals()[payload.role]

    # Idempotent, and done here rather than only at seed time so a database
    # created before this existed still gets the demo state on first use.
    ensure_demo_environment(db)

    user = db.get(User, principal.user_id)
    if user is None:  # pragma: no cover - ensure_demo_environment just created it
        raise HTTPException(status_code=500, detail="Demo principal could not be created.")

    request_id = getattr(request.state, "request_id", None)
    logger.info("demo login issued", extra={"user_id": user.id, "role": user.role, "request_id": request_id})
    _audit.log_event(
        db,
        session_id="demo_login",
        user_id=user.id,
        event_type="demo_login",
        actor="system",
        reason=f"Development-only demo sign-in as {user.role}. Not reachable outside APP_ENV=development.",
        request_id=request_id,
    )

    return DemoLoginResult(
        token=create_access_token(sub=user.id, email=user.email, role=user.role),
        user_id=user.id,
        email=user.email,
        role=user.role or principal.role,
    )
