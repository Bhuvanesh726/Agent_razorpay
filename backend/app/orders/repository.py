"""Order persistence. The one function that matters is `get_or_create`:
insert first, and if the DB's UNIQUE constraint on idempotency_key rejects
it as a duplicate, catch that and re-select the row that won the race —
never "does it exist? then insert" (that check-then-act pattern is exactly
what lets two concurrent requests both pass the check and both insert).
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import logger
from app.models.order import Order, Payment
from app.orders.state_machine import OrderStatus
from app.testing.chaos import ChaosFault, is_active


def find_by_idempotency_key(db: Session, idempotency_key: str) -> Order | None:
    return db.scalar(select(Order).where(Order.idempotency_key == idempotency_key))


def list_by_user(db: Session, user_id: str, *, limit: int = 10) -> list[Order]:
    stmt = select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def list_all(db: Session, *, limit: int = 200) -> list[Order]:
    """Every order, any buyer — backs the merchant-wide orders view
    (app/routers/orders.py). Unscoped by design: a merchant reviewing
    incoming orders is the one caller allowed to see across buyers."""
    stmt = select(Order).order_by(Order.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


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

    if is_active(ChaosFault.DB_CONFLICT):
        _simulate_concurrent_winner(db, idempotency_key, user_id, session_id, cart_id, amount_paise, currency)

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


def _simulate_concurrent_winner(
    db: Session, idempotency_key: str, user_id: str, session_id: str, cart_id: int, amount_paise: int, currency: str
) -> None:
    """Chaos: genuinely inserts a competing row — via a separate, independent
    session/transaction bound to the *same engine* as the caller's session
    (not the global default — a test using an isolated in-memory DB must see
    a real collision too, not silently miss it) — with the same idempotency
    key right before our own insert attempt below. This makes
    `get_or_create`'s IntegrityError handling fire for real, against a real
    UNIQUE constraint violation, exactly as it would for two truly concurrent
    requests (see tests/test_order_repository_concurrency.py for the
    un-injected version of this same race)."""
    side_session = sessionmaker(bind=db.get_bind())()
    try:
        side_session.add(
            Order(
                idempotency_key=idempotency_key,
                user_id=user_id,
                session_id=session_id,
                cart_id=cart_id,
                amount_paise=amount_paise,
                currency=currency,
                status=OrderStatus.PENDING.value,
            )
        )
        side_session.commit()
        logger.warning("chaos: injected a competing concurrent order insert", extra={"idempotency_key": idempotency_key})
    finally:
        side_session.close()


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
