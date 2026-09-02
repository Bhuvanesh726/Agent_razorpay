"""The order state machine. Pure — no DB, no I/O — so every transition rule
is testable without a running server.

PENDING              → order row exists, no Razorpay order yet
AWAITING_CONFIRMATION → a Razorpay order exists, waiting on Checkout to complete
PAID                  → signature verified, terminal
FAILED                → declined, signature invalid, or Razorpay error; NOT
                         terminal — a fresh attempt against the same order
                         (same idempotency key) is allowed
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
    OrderStatus.FAILED: frozenset({OrderStatus.AWAITING_CONFIRMATION, OrderStatus.CANCELLED}),
    OrderStatus.PAID: frozenset(),  # terminal
    OrderStatus.CANCELLED: frozenset(),  # terminal
}


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def require_transition(current: OrderStatus, target: OrderStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)
