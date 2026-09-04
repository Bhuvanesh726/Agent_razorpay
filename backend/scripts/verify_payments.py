"""Checks every order and payment in the local database against Razorpay's
LIVE API and prints, per row, whether Razorpay actually knows about it.

The point is falsifiability. This project's own logs and its own `orders`
table will happily say "PAID" for a payment that Razorpay has never seen —
because some capture paths in this codebase sign a synthetic payment id
locally rather than moving money through Razorpay's rails. Reading our own
database to confirm our own claim proves nothing. This script asks the only
party that can actually settle the question.

Run from the backend/ directory:
    python scripts/verify_payments.py

Requires RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET (test mode) in .env — the same
credentials the app itself uses. Read-only: it only ever fetches.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import razorpay  # noqa: E402
from razorpay.errors import BadRequestError  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.order import Order, Payment  # noqa: E402


def _fetch(fn, entity_id):
    """Returns (found: bool, payload_or_error)."""
    if not entity_id:
        return False, "no id recorded locally"
    try:
        return True, fn(entity_id)
    except BadRequestError as e:
        return False, str(e)
    except Exception as e:  # network/auth/etc — report, never pretend
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    db = SessionLocal()

    print(f"Razorpay key : {settings.razorpay_key_id}")
    print(f"Database     : {settings.database_url}")
    print("=" * 100)

    real_payments = 0
    synthetic_payments = 0
    real_orders = 0
    missing_orders = 0

    try:
        orders = db.query(Order).order_by(Order.id).all()
        for order in orders:
            found, payload = _fetch(client.order.fetch, order.razorpay_order_id)
            if found:
                real_orders += 1
                rp = (
                    f"REAL   amount={payload['amount']} status={payload['status']} "
                    f"attempts={payload.get('attempts')}"
                )
            else:
                missing_orders += 1
                rp = f"NOT IN RAZORPAY  ({payload})"

            print(
                f"\nOrder #{order.id:<4} local_status={order.status:<22} "
                f"amount_paise={order.amount_paise:<8} razorpay_order_id={order.razorpay_order_id}"
            )
            print(f"    order  -> {rp}")

            payments = db.query(Payment).filter(Payment.order_id == order.id).all()
            if not payments:
                print("    payment-> (none recorded locally)")
            for p in payments:
                found, payload = _fetch(client.payment.fetch, p.razorpay_payment_id)
                if found:
                    real_payments += 1
                    detail = (
                        f"REAL   status={payload['status']} method={payload.get('method')} "
                        f"amount={payload['amount']} captured={payload.get('captured')}"
                    )
                else:
                    synthetic_payments += 1
                    detail = f"NOT IN RAZORPAY  ({payload})"
                print(
                    f"    payment-> local_status={p.status:<9} method={str(p.method):<18} "
                    f"id={p.razorpay_payment_id}"
                )
                print(f"               {detail}")
    finally:
        db.close()

    print("\n" + "=" * 100)
    print(f"Orders   : {real_orders} real in Razorpay, {missing_orders} not found")
    print(f"Payments : {real_payments} real in Razorpay, {synthetic_payments} not found")
    print(
        "\nA 'NOT IN RAZORPAY' payment was captured locally with a self-signed id "
        "(pay_auto_* / pay_test_*).\nSee docs/PAYMENT-REALITY.md for exactly why those paths exist "
        "and what they do and don't prove."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
