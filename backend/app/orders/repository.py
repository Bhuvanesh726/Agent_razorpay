"""Order persistence. The one function that matters is `get_or_create`:
insert first, and if the DB's UNIQUE constraint on idempotency_key rejects
it as a duplicate, catch that and re-select the row that won the race —
never "does it exist? then insert" (that check-then-act pattern is exactly
what lets two concurrent requests both pass the check and both insert).
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.order import Order, Payment
from app.orders.state_machine import OrderStatus


def find_by_idempotency_key(db: Session, idempotency_key: str) -> Order | None:
    return db.scalar(select(Order).where(Order.idempotency_key == idempotency_key))


def find_by_razorpay_order_id(db: Session, razorpay_order_id: str) -> Order | None:
    return db.scalar(select(Order).where(Order.razorpay_order_id == razorpay_order_id))


def get_by_id(db: Session, order_id: int) -> Order | None:
    return db.get(Order, order_id)


def get_or_create(
    db: Session,
    *,
    idempotency_key: str,
    user_id: str,
    session_id: str,
    cart_id: int,
    amount_paise: int,
    currency: str,
) -> tuple[Order, bool]:
    """Returns (order, was_created). `was_created=False` means a prior order
    for this exact idempotency key already existed — the caller must treat
    this as "found", never create a second row, and log it as a prevented
    duplicate."""
    existing = find_by_idempotency_key(db, idempotency_key)
    if existing is not None:
        return existing, False

    order = Order(
        idempotency_key=idempotency_key,
        user_id=user_id,
        session_id=session_id,
        cart_id=cart_id,
        amount_paise=amount_paise,
        currency=currency,
        status=OrderStatus.PENDING.value,
    )
    db.add(order)
    try:
        db.commit()
    except IntegrityError:
        # Lost the race: another transaction inserted the same key between
        # our SELECT above and this INSERT. The DB is the source of truth —
        # roll back our attempt and return whichever row actually landed.
        db.rollback()
        winner = find_by_idempotency_key(db, idempotency_key)
        if winner is None:
            raise  # a different constraint failed; don't swallow that
        return winner, False

    db.refresh(order)
    return order, True


def save(db: Session, order: Order) -> Order:
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def add_payment(db: Session, payment: Payment) -> Payment:
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment
