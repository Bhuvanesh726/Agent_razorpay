from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.cart import Cart, CartItem
from app.repositories import cart_repo, product_repo
from app.schemas.cart import CartItemCreate, CartItemOut, CartOut
from app.services.pricing import effective_price_paise


def _to_cart_out(cart: Cart) -> CartOut:
    items = [
        CartItemOut(
            id=item.id,
            product_id=item.product_id,
            sku=item.product.sku,
            name=item.product.name,
            quantity=item.quantity,
            unit_price_paise=item.unit_price_paise,
        )
        for item in cart.items
    ]
    return CartOut(
        id=cart.id,
        user_id=cart.user_id,
        status=cart.status,
        created_at=cart.created_at,
        items=items,
    )


def get_cart(db: Session, user_id: str) -> CartOut:
    cart = cart_repo.get_or_create_active_cart(db, user_id)
    db.commit()
    db.refresh(cart)
    return _to_cart_out(cart)


def add_item(db: Session, user_id: str, payload: CartItemCreate) -> CartOut:
    product = product_repo.get_by_sku(db, payload.sku)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product '{payload.sku}' not found")

    cart = cart_repo.get_or_create_active_cart(db, user_id)

    existing = cart_repo.get_item_by_product(db, cart.id, product.id)
    if existing is not None:
        existing.quantity += payload.quantity
    else:
        cart_repo.add_item(
            db,
            CartItem(
                cart_id=cart.id,
                product_id=product.id,
                quantity=payload.quantity,
                # Snapshot the price now — the cart total must not drift if
                # the catalog price (or an active discount) changes later.
                unit_price_paise=effective_price_paise(product),
                user_id=user_id,
            ),
        )

    db.commit()
    cart = cart_repo.get_active_cart(db, user_id)
    return _to_cart_out(cart)


def delete_item(db: Session, user_id: str, item_id: int) -> CartOut:
    item = cart_repo.get_item(db, item_id)
    if item is None or item.user_id != user_id:
        raise HTTPException(status_code=404, detail=f"Cart item {item_id} not found")

    cart_repo.delete_item(db, item)
    db.commit()

    cart = cart_repo.get_or_create_active_cart(db, user_id)
    return _to_cart_out(cart)
