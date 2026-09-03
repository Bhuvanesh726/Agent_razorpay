"""Role selection — Layer 4.8. Replaces Layer 4.7's MERCHANT_EMAILS
allowlist entirely: a new Google login gets no role at all
(app/auth/oauth_router.py no longer assigns one), resolves to PrincipalType
"pending" (app/auth/principal.py), and is rejected by every ordinary
BUYER/MERCHANT-gated endpoint until they pick one here. One click, one
write, done — no wizard. See docs/048-demand-loop.md.

Also hosts the dev-only role switch ("demo both sides without two Google
accounts") — same dev_env gate as /api/payments/test-complete and
X-Chaos-Fault, checked after auth so an already-BUYER-or-MERCHANT principal
is required even in development.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_principal
from app.auth.principal import Principal
from app.auth.routing import AuthRequirement, SecureAPIRoute, requires
from app.auth.security import create_access_token
from app.core.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.onboarding import RoleChoice, RoleChoiceResult

router = APIRouter(tags=["onboarding"], route_class=SecureAPIRoute)


def _set_role_and_reissue(db: Session, user_id: str, role: str) -> RoleChoiceResult:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    user.role = role
    db.commit()
    token = create_access_token(sub=user.id, email=user.email, role=user.role)
    return RoleChoiceResult(role=user.role, token=token)


@router.post("/api/onboarding/role", response_model=RoleChoiceResult)
@requires(AuthRequirement.PENDING)
def choose_role(
    payload: RoleChoice, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> RoleChoiceResult:
    return _set_role_and_reissue(db, principal.user_id, payload.role)


@router.post("/api/dev/switch-role", response_model=RoleChoiceResult)
@requires(AuthRequirement.BUYER, AuthRequirement.MERCHANT)
def switch_role(
    payload: RoleChoice, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> RoleChoiceResult:
    if settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Not found.")
    return _set_role_and_reissue(db, principal.user_id, payload.role)
