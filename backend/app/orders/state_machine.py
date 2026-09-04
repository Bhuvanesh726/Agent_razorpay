"""The order state machine. Pure — no DB, no I/O — so every transition rule
is testable without a running server.

PENDING              → order row exists, no Razorpay order yet
AWAITING_CONFIRMATION → a Razorpay order exists, waiting on Checkout to complete
PAID                  → signature verified, terminal
FAILED                → declined, signature invalid, or Razorpay error; NOT
                         terminal — a fresh attempt against the same order
                         (same idempotency key) is allowed, and a verified
                         signature arriving late can still carry it to PAID
                         (see FAILED → PAID below)
CANCELLED             → abandoned before payment; terminal
"""

from enum import Enum


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InvalidTransitionError(Exception):
    def __init__(self, current: "OrderStatus", target: "OrderStatus"):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition order from {current.value} to {target.value}")


ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset({OrderStatus.AWAITING_CONFIRMATION, OrderStatus.FAILED, OrderStatus.CANCELLED}),
    OrderStatus.AWAITING_CONFIRMATION: frozenset({OrderStatus.PAID, OrderStatus.FAILED, OrderStatus.CANCELLED}),
    # A failed attempt can retry — same order, a fresh Razorpay Checkout pass.
    #
    # FAILED → PAID is permitted because Razorpay is the authority on whether
    # money moved, and our FAILED is only ever a local belief. Razorpay
    # Checkout can fire its failure callback before its success callback
    # within a single session (a declined first attempt, then a successful
    # retry, reported out of order). Refusing the later success left order #23
    # recorded FAILED while Razorpay held a real captured ₹275 payment — a
    # reconciliation gap where our own records were simply wrong. See
    # Failures.md.
    #
    # This is NOT a hole in the invariant that matters: mark_paid is only
    # reachable after gateway.verify_signature() returns True
    # (app/routers/payments.py and app/agent/harness.py are its only callers),
    # so reaching PAID still requires an HMAC we can verify against the
    # merchant secret. What changes is only which *prior local state* is
    # allowed to block that proof.
    #
    # The reverse, PAID → FAILED, remains forbidden: a stale or duplicated
    # failure callback must never downgrade a payment we verified.
    OrderStatus.FAILED: frozenset({OrderStatus.AWAITING_CONFIRMATION, OrderStatus.PAID, OrderStatus.CANCELLED}),
    OrderStatus.PAID: frozenset(),  # terminal
    OrderStatus.CANCELLED: frozenset(),  # terminal
}


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def require_transition(current: OrderStatus, target: OrderStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)
