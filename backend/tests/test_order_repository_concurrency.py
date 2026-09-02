"""Proves the race-safety claim with real concurrent execution, not a
simulated single-threaded stand-in. Uses a file-based SQLite DB (an
in-memory `:memory:` DB is isolated per-connection, so it can't demonstrate
a genuine cross-connection race) with two threads, each on its own
SQLAlchemy Session, both racing to create an order for the same
idempotency key at the same instant via a barrier.
"""

import os
import tempfile
import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.cart import Cart
from app.models.product import Product
from app.orders import repository as order_repo


def _make_file_engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=engine)
    return engine, path


def test_two_concurrent_order_creations_produce_exactly_one_order():
    engine, path = _make_file_engine()
    session_factory = sessionmaker(bind=engine)

    # Seed a product + cart once, visible to both threads.
    setup = session_factory()
    product = Product(
        sku="PET-001", name="Pedigree", brand="Pedigree", category="pet_supplies",
        price_paise=74000, unit="3kg", stock=25, description="", tags=["dog"],
    )
    cart = Cart(user_id="user_demo", status="active")
    setup.add_all([product, cart])
    setup.commit()
    cart_id = cart.id
    setup.close()

    idempotency_key = "race-test-key-fixed"
    results: list[tuple[int, bool]] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def attempt():
        db = session_factory()
        try:
            barrier.wait(timeout=5)  # maximize the chance both threads insert at the same instant
            order, created = order_repo.get_or_create(
                db,
                idempotency_key=idempotency_key,
                user_id="user_demo",
                session_id="sess-race",
                cart_id=cart_id,
                amount_paise=74000,
                currency="INR",
            )
            results.append((order.id, created))
        except Exception as e:  # captured and asserted on below, not swallowed
            errors.append(e)
        finally:
            db.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    try:
        assert not errors, f"unexpected errors during concurrent creation: {errors}"
        assert len(results) == 2

        order_ids = {order_id for order_id, _created in results}
        assert len(order_ids) == 1, f"expected exactly one order, got ids: {order_ids}"

        created_flags = sorted(created for _order_id, created in results)
        assert created_flags == [False, True], "exactly one thread should have created the row, the other found it"

        verify = session_factory()
        try:
            count = verify.query(order_repo.Order).filter_by(idempotency_key=idempotency_key).count()
            assert count == 1
        finally:
            verify.close()
    finally:
        engine.dispose()
        os.remove(path)
