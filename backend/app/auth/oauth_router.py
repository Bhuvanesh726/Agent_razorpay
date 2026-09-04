"""Google OAuth for human principals only. Buyers and merchants log in here
via the exact same flow — Google has no concept of "merchant," so role is
assigned by this backend at first login (settings.merchant_email_set), not
by anything Google returns. Agents never touch this file: they present a
pre-issued key on every call instead (app/auth/principal.py), which is the
whole point of Layer 4.7's principal split — see docs/047-principals.md.
"""

from urllib.parse import quote

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.auth.deps import get_principal
from app.auth.principal import Principal
from app.auth.routing import AuthRequirement, SecureAPIRoute, public, requires
from app.auth.security import create_access_token
from app.core.config import settings
from app.core.logging import logger
from app.database import get_db
from app.models.user import User

router = APIRouter(tags=["auth"], route_class=SecureAPIRoute)
_audit = AuditService()

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def _readable_oauth_error(e: Exception) -> str:
    """authlib's own exception text (e.g. "mismatching_state: CSRF Warning!
    State not equal in request and response.") is accurate but not
    something to hand a user — translate the failure modes actually
    possible here into plain language, and fall back to a generic message
    for anything unanticipated rather than leaking internals."""
    if isinstance(e, OAuthError):
        return (
            "Your sign-in session could not be verified. This usually happens if the browser "
            "didn't send back the cookie set when you clicked 'Sign in with Google' — often "
            "because you waited too long on Google's consent screen, or opened the link in a "
            "different browser/tab than the one that started it. Please try signing in again, "
            "starting from this page."
        )
    return "Sign-in failed unexpectedly. Please try again — if this keeps happening, contact support."


@router.get("/api/auth/google/login")
@public
async def google_login(request: Request):
    # Derived from the incoming request rather than settings.google_redirect_uri
    # fixed to one host: this is what makes the round trip work whether this
    # endpoint was reached via localhost:8842 or 127.0.0.1:8842. The
    # SessionMiddleware cookie that carries the CSRF state below is
    # host-scoped, so login and callback MUST share a host for the state
    # check to ever pass — see docs/047-principals.md and the
    # MismatchingStateError this replaced. Both exact host variants need to
    # be registered as "Authorized redirect URIs" on the Google OAuth
    # client for this to work from either.
    redirect_uri = str(request.url_for("google_callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/api/auth/google/callback")
@public
async def google_callback(request: Request, db: Session = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    frontend_origin = settings.frontend_url
    email: str | None = None

    try:
        token = await oauth.google.authorize_access_token(request)
        userinfo = token.get("userinfo")
        if userinfo is None:
            userinfo = await oauth.google.parse_id_token(request, token)

        email = userinfo["email"]
        sub = userinfo["sub"]
        name = userinfo.get("name") or email

        user = db.query(User).filter(User.google_sub == sub).first()
        if user is None:
            user = db.query(User).filter(User.email == email).first()
        if user is None:
            # Everyone starts as a BUYER. Layer 4.8 used to park a new user
            # at /onboarding to pick a role first, but in this project one
            # person is legitimately both sides — they need to shop *and* see
            # the merchant view of their own store — so a one-time,
            # irreversible-feeling choice was the wrong shape. The role switch
            # (app/auth/role_router.py) is the supported way to move between
            # them, and it can be used as often as you like.
            user = User(id=f"google_{sub}", email=email, name=name, google_sub=sub, role="BUYER")
            db.add(user)
        else:
            user.google_sub = sub
            user.name = name
        db.commit()

        jwt_token = create_access_token(sub=user.id, email=user.email, role=user.role)
        return RedirectResponse(url=f"{frontend_origin}/login/callback?token={jwt_token}")

    except Exception as e:
        db.rollback()
        message = _readable_oauth_error(e)
        # Every other failure path in this project explains itself in the
        # audit log and the server log — a bare 500 on the one path a human
        # actually clicks through by hand was the gap Layer 4.7 left open.
        logger.error(
            "google oauth callback failed",
            extra={"error": str(e), "error_type": type(e).__name__, "request_id": request_id},
            exc_info=True,
        )
        _audit.log_event(
            db,
            session_id="oauth_login",
            user_id=email or "unknown",
            event_type="login_failed",
            actor="system",
            decision="DENY",
            reason=f"{type(e).__name__}: {e}",
            request_id=request_id,
        )
        return RedirectResponse(url=f"{frontend_origin}/login?error={quote(message)}")


@router.get("/api/auth/me")
@requires(AuthRequirement.BUYER, AuthRequirement.MERCHANT, AuthRequirement.AGENT)
def get_me(principal: Principal = Depends(get_principal)) -> dict:
    return {
        "type": principal.type,
        "user_id": principal.user_id,
        "email": principal.email,
        "role": principal.role,
        "credential_id": principal.credential_id,
    }
