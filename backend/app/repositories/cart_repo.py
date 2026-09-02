from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.cart import Cart, CartItem


def get_active_cart(db: Session, user_id: str) -> Cart | None:
    stmt = (
        select(Cart)
        .options(selectinload(Cart.items).selectinload(CartItem.product))
        .where(Cart.user_id == user_id, Cart.status == "active")
    )
    return db.scalar(stmt)


def create_cart(db: Session, user_id: str) -> Cart:
    cart = Cart(user_id=user_id, status="active")
    db.add(cart)
    db.flush()
    return cart


def get_or_create_active_cart(db: Session, user_id: str) -> Cart:
    cart = get_active_cart(db, user_id)
    if cart is None:
        cart = create_cart(db, user_id)
    return cart


def get_item_by_product(db: Session, cart_id: int, product_id: int) -> CartItem | None:
    stmt = select(CartItem).where(
        CartItem.cart_id == cart_id, CartItem.product_id == product_id
    )
    return db.scalar(stmt)


def get_item(db: Session, item_id: int) -> CartItem | None:
    return db.get(CartItem, item_id)


def get_by_id(db: Session, cart_id: int) -> Cart | None:
    return db.get(Cart, cart_id)


def mark_checked_out(db: Session, cart: Cart) -> None:
    cart.status = "checked_out"
    db.flush()


def add_item(db: Session, item: CartItem) -> CartItem:
    db.add(item)
    db.flush()
    return item


def delete_item(db: Session, item: CartItem) -> None:
    db.delete(item)
