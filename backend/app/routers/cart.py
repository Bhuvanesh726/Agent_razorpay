from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.schemas.cart import CartItemCreate, CartOut
from app.services import cart_service

router = APIRouter(tags=["cart"])

# No auth yet (Layer 1+). Every request acts on the single demo user's cart.
CURRENT_USER_ID = settings.default_user_id


@router.get("/api/cart", response_model=CartOut)
def get_cart(db: Session = Depends(get_db)) -> CartOut:
    return cart_service.get_cart(db, CURRENT_USER_ID)


@router.post("/api/cart/items", response_model=CartOut)
def add_cart_item(payload: CartItemCreate, db: Session = Depends(get_db)) -> CartOut:
    return cart_service.add_item(db, CURRENT_USER_ID, payload)


@router.delete("/api/cart/items/{item_id}", response_model=CartOut)
def delete_cart_item(item_id: int, db: Session = Depends(get_db)) -> CartOut:
    return cart_service.delete_item(db, CURRENT_USER_ID, item_id)
