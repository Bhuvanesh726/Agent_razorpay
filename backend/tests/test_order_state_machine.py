import pytest

from app.orders.state_machine import InvalidTransitionError, OrderStatus, can_transition, require_transition


VALID_TRANSITIONS = [
    (OrderStatus.PENDING, OrderStatus.AWAITING_CONFIRMATION),
    (OrderStatus.PENDING, OrderStatus.FAILED),
    (OrderStatus.PENDING, OrderStatus.CANCELLED),
    (OrderStatus.AWAITING_CONFIRMATION, OrderStatus.PAID),
    (OrderStatus.AWAITING_CONFIRMATION, OrderStatus.FAILED),
    (OrderStatus.AWAITING_CONFIRMATION, OrderStatus.CANCELLED),
    (OrderStatus.FAILED, OrderStatus.AWAITING_CONFIRMATION),  # retry
    (OrderStatus.FAILED, OrderStatus.CANCELLED),
    # A verified signature arriving after a failure callback. Razorpay is the
    # authority on whether money moved; our FAILED is only a local belief, and
    # refusing this left order #23 recorded FAILED against a real captured
    # payment. See Failures.md and tests/test_failed_order_recovery.py.
    (OrderStatus.FAILED, OrderStatus.PAID),
]

INVALID_TRANSITIONS = [
    (OrderStatus.PENDING, OrderStatus.PAID),  # can't skip straight to paid
    (OrderStatus.AWAITING_CONFIRMATION, OrderStatus.PENDING),  # no going backwards
    (OrderStatus.PAID, OrderStatus.FAILED),  # paid is terminal
    (OrderStatus.PAID, OrderStatus.AWAITING_CONFIRMATION),
    (OrderStatus.PAID, OrderStatus.CANCELLED),
    (OrderStatus.PAID, OrderStatus.PENDING),
    (OrderStatus.CANCELLED, OrderStatus.AWAITING_CONFIRMATION),  # cancelled is terminal
    (OrderStatus.CANCELLED, OrderStatus.PAID),
]


@pytest.mark.parametrize("current,target", VALID_TRANSITIONS)
def test_valid_transitions_allowed(current, target):
    assert can_transition(current, target) is True
    require_transition(current, target)  # must not raise


@pytest.mark.parametrize("current,target", INVALID_TRANSITIONS)
def test_invalid_transitions_rejected(current, target):
    assert can_transition(current, target) is False
    with pytest.raises(InvalidTransitionError):
        require_transition(current, target)


def test_terminal_states_have_no_outgoing_transitions():
    assert can_transition(OrderStatus.PAID, OrderStatus.PAID) is False
    for status in OrderStatus:
        assert can_transition(OrderStatus.PAID, status) is False
        assert can_transition(OrderStatus.CANCELLED, status) is False
