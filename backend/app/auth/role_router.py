"""Switching between the buyer and merchant views.

Every Google login starts as a BUYER (app/auth/oauth_router.py). There is no
role-selection step: in this project one person is legitimately both sides of
the marketplace — they shop, and they look at the merchant view of their own
store — so asking them to commit to one at signup was answering a question
nobody had. They switch here instead, as often as they want.

Dev-gated, on the same `app_env == "development"` check as
/api/payments/test-complete and X-Chaos-Fault, and checked after auth so an
already-BUYER-or-MERCHANT principal is required even in development. A real
deployment with distinct buyer and merchant accounts would not ship this.
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

router = APIRouter(tags=["roles"], route_class=SecureAPIRoute)


def _set_role_and_reissue(db: Session, user_id: str, role: str) -> RoleChoiceResult:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    user.role = role
    db.commit()
    token = create_access_token(sub=user.id, email=user.email, role=user.role)
    return RoleChoiceResult(role=user.role, token=token)


@router.post("/api/dev/switch-role", response_model=RoleChoiceResult)
@requires(AuthRequirement.BUYER, AuthRequirement.MERCHANT)
def switch_role(
    payload: RoleChoice, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> RoleChoiceResult:
    if settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Not found.")
    return _set_role_and_reissue(db, principal.user_id, payload.role)
