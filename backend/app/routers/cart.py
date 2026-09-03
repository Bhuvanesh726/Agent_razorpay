from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import get_principal
from app.auth.principal import Principal
from app.auth.routing import AuthRequirement, SecureAPIRoute, requires
from app.database import get_db
from app.schemas.cart import CartItemCreate, CartOut
from app.services import cart_service

router = APIRouter(tags=["cart"], route_class=SecureAPIRoute)

# BUYER only, deliberately — not AGENT. These raw REST endpoints mutate the
# cart directly with no policy engine in front of them (see
# docs/045-catalog.md); an agent must go through /api/agent/chat instead,
# the one path RevokedCredentialRule/AgentScopeRule/AgentSpendLimitRule
# actually run on. Letting an agent hit this endpoint would be a real
# bypass of "same rules, same enforcement," not a convenience.


@router.get("/api/cart", response_model=CartOut)
@requires(AuthRequirement.BUYER)
def get_cart(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> CartOut:
    return cart_service.get_cart(db, principal.user_id)


@router.post("/api/cart/items", response_model=CartOut)
@requires(AuthRequirement.BUYER)
def add_cart_item(
    payload: CartItemCreate, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> CartOut:
    return cart_service.add_item(db, principal.user_id, payload)


@router.delete("/api/cart/items/{item_id}", response_model=CartOut)
@requires(AuthRequirement.BUYER)
def delete_cart_item(
    item_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> CartOut:
    return cart_service.delete_item(db, principal.user_id, item_id)
