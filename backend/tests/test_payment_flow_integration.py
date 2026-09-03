"""End-to-end payment flow with the LLM gateway stubbed (scripted responses)
and the Razorpay order-creation call mocked (no real network) — but real
signature verification (pure local HMAC, same as production) and a real DB.

Covers the definition-of-done: agent proposes payment -> user confirms ->
signature verified -> order PAID; a duplicate verify call does not double-
charge; a spend-cap-violating cart is denied before any order is created.
"""

import hashlib
import hmac
import json
import types
from unittest.mock import patch

from app.agent import harness
from app.auth.principal import Principal
from app.core.config import settings
from app.llm.gateway import GatewayResult
from app.llm.gateway import ToolCall as GatewayToolCall
from app.orders import repository as order_repo
from app.orders.state_machine import OrderStatus
from app.payments.gateway import RazorpayOrder
from app.repositories import product_repo
from app.routers.payments import report_payment_failed, verify_payment
# Aliased on import: a bare `test_complete_payment` name would be collected by
# pytest as a test function (it matches the test_* pattern) and fail — it's
# a FastAPI endpoint that requires arguments, not a test.
from app.routers.payments import test_complete_payment as complete_test_payment
from app.schemas.payments import PaymentFailedRequest, VerifyPaymentRequest


def seed_pedigree(db):
    product_repo.upsert(
        db,
        {
            "sku": "PET-001",
            "name": "Pedigree Adult Dry Dog Food",
            "brand": "Pedigree",
            "category": "pet_supplies",
            "price_paise": 74000,
            "unit": "3kg pack",
            "stock": 25,
            "description": "dog food",
            "tags": ["dog"],
        },
    )
    db.commit()


def _tool_call_response(name: str, arguments: dict) -> GatewayResult:
    return GatewayResult(
        content=None,
        tool_calls=[GatewayToolCall(id="call_1", name=name, arguments_raw=json.dumps(arguments))],
        model_used="test-model",
        fallback_used=False,
        latency_ms=1,
    )


def _final_response(content: str) -> GatewayResult:
    return GatewayResult(content=content, tool_calls=[], model_used="test-model", fallback_used=False, latency_ms=1)


def _fake_request():
    return types.SimpleNamespace(state=types.SimpleNamespace())


def _buyer_principal(user_id: str = "user_demo") -> Principal:
    return Principal(type="buyer", user_id=user_id, role="BUYER")


def _sign(order_id: str, payment_id: str) -> str:
    message = f"{order_id}|{payment_id}"
    return hmac.new(settings.razorpay_key_secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _propose_and_confirm_payment(db, session_id: str, budget_paise: int, razorpay_order_id: str):
    """Runs the agent up to a confirmed initiate_payment call, with Razorpay's
    order-creation mocked (no network). Returns the harness confirm result."""
    scripted = iter([_tool_call_response("initiate_payment", {})])
    with (
        patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)),
        patch(
            "app.orders.service.gateway.create_order",
            return_value=RazorpayOrder(
                razorpay_order_id=razorpay_order_id, amount_paise=74000, currency="INR", receipt="order-1"
            ),
        ),
    ):
        proposal = harness.handle_chat(db, session_id, "user_demo", "pay for my cart", budget_paise, "req-1")
        assert proposal.status == "awaiting_confirmation"
        assert proposal.pending["tool_name"] == "initiate_payment"

        scripted_after = iter([_final_response("Order created, please complete checkout.")])
        with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_after)):
            confirmed = harness.handle_confirm(db, session_id, "user_demo", True, "req-2")

    return confirmed


def test_full_payment_flow_succeeds_and_resets_cart(db_session):
    seed_pedigree(db_session)
    from app.repositories import cart_repo
    from app.schemas.cart import CartItemCreate
    from app.services import cart_service

    cart_service.add_item(db_session, "user_demo", CartItemCreate(sku="PET-001", quantity=1))
    original_cart = cart_repo.get_or_create_active_cart(db_session, "user_demo")
    original_cart_id = original_cart.id

    confirmed = _propose_and_confirm_payment(db_session, "sess-pay-1", 100_000, "order_rzp_fake1")
    assert confirmed.status == "completed"
    assert confirmed.payment is not None
    assert confirmed.payment["razorpay_order_id"] == "order_rzp_fake1"
    assert confirmed.payment["amount_paise"] == 74000
    assert "razorpay_key_id" in confirmed.payment

    order = order_repo.find_by_razorpay_order_id(db_session, "order_rzp_fake1")
    assert order is not None
    assert order.status == OrderStatus.AWAITING_CONFIRMATION.value

    # Browser completes Razorpay Checkout; a real, valid signature is posted back.
    payment_id = "pay_rzp_fake1"
    signature = _sign("order_rzp_fake1", payment_id)
    result = verify_payment(
        VerifyPaymentRequest(razorpay_order_id="order_rzp_fake1", razorpay_payment_id=payment_id, razorpay_signature=signature),
        _fake_request(),
        _buyer_principal(),
        db_session,
    )
    assert result.status == "PAID"

    db_session.refresh(order)
    assert order.status == OrderStatus.PAID.value
    assert len(order.payments) == 1
    assert order.payments[0].status == "captured"
    assert order.payments[0].razorpay_payment_id == payment_id

    # Cart reset: old cart checked out, a fresh active cart exists.
    db_session.refresh(original_cart)
    assert original_cart.status == "checked_out"
    new_cart = cart_repo.get_or_create_active_cart(db_session, "user_demo")
    assert new_cart.id != original_cart_id
    assert new_cart.items == []

    trail = harness._audit.get_trail(db_session, "sess-pay-1")
    event_types = [e.event_type for e in trail]
    assert "order_created" in event_types
    assert "razorpay_order_created" in event_types


def test_double_verify_call_does_not_double_charge(db_session):
    seed_pedigree(db_session)
    from app.schemas.cart import CartItemCreate
    from app.services import cart_service

    cart_service.add_item(db_session, "user_demo", CartItemCreate(sku="PET-001", quantity=1))

    confirmed = _propose_and_confirm_payment(db_session, "sess-pay-2", 100_000, "order_rzp_fake2")
    assert confirmed.payment is not None

    payment_id = "pay_rzp_fake2"
    signature = _sign("order_rzp_fake2", payment_id)
    payload = VerifyPaymentRequest(
        razorpay_order_id="order_rzp_fake2", razorpay_payment_id=payment_id, razorpay_signature=signature
    )

    first = verify_payment(payload, _fake_request(), _buyer_principal(), db_session)
    second = verify_payment(payload, _fake_request(), _buyer_principal(), db_session)  # simulates a rapid double-click / retry

    assert first.status == "PAID"
    assert second.status == "PAID"
    assert second.message.startswith("This order was already paid")

    order = order_repo.find_by_razorpay_order_id(db_session, "order_rzp_fake2")
    assert len(order.payments) == 1, "exactly one charge, not two"

    trail = harness._audit.get_trail(db_session, "sess-pay-2")
    duplicate_events = [e for e in trail if e.event_type == "duplicate_payment_prevented"]
    assert len(duplicate_events) == 1


def test_tampered_signature_is_rejected_and_order_fails(db_session):
    seed_pedigree(db_session)
    from app.schemas.cart import CartItemCreate
    from app.services import cart_service

    cart_service.add_item(db_session, "user_demo", CartItemCreate(sku="PET-001", quantity=1))
    confirmed = _propose_and_confirm_payment(db_session, "sess-pay-3", 100_000, "order_rzp_fake3")
    assert confirmed.payment is not None

    result = verify_payment(
        VerifyPaymentRequest(
            razorpay_order_id="order_rzp_fake3", razorpay_payment_id="pay_rzp_fake3", razorpay_signature="0" * 64
        ),
        _fake_request(),
        _buyer_principal(),
        db_session,
    )
    assert result.status == "FAILED"

    order = order_repo.find_by_razorpay_order_id(db_session, "order_rzp_fake3")
    assert order.status == OrderStatus.FAILED.value
    assert order.payments[0].status == "failed"
    assert order.payments[0].error_code == "signature_verification_failed"

    trail = harness._audit.get_trail(db_session, "sess-pay-3")
    assert any(e.event_type == "signature_rejected" and e.decision == "DENY" for e in trail)


def test_payment_failed_endpoint_records_declined_test_card(db_session):
    seed_pedigree(db_session)
    from app.schemas.cart import CartItemCreate
    from app.services import cart_service

    cart_service.add_item(db_session, "user_demo", CartItemCreate(sku="PET-001", quantity=1))
    confirmed = _propose_and_confirm_payment(db_session, "sess-pay-4", 100_000, "order_rzp_fake4")
    assert confirmed.payment is not None

    result = report_payment_failed(
        PaymentFailedRequest(razorpay_order_id="order_rzp_fake4", error_code="BAD_REQUEST_ERROR", error_description="Card declined"),
        _fake_request(),
        _buyer_principal(),
        db_session,
    )
    assert result.status == "FAILED"

    order = order_repo.find_by_razorpay_order_id(db_session, "order_rzp_fake4")
    assert order.status == OrderStatus.FAILED.value
    assert order.payments[0].error_code == "BAD_REQUEST_ERROR"


def test_payment_denied_when_cart_violates_spend_cap(db_session):
    """No order is ever created for a cart the policy engine denies at
    payment time — DENY happens before order_service is touched at all."""
    seed_pedigree(db_session)
    from app.schemas.cart import CartItemCreate
    from app.services import cart_service

    cart_service.add_item(db_session, "user_demo", CartItemCreate(sku="PET-001", quantity=1))  # 74000 paise

    scripted = iter(
        [
            _tool_call_response("initiate_payment", {}),
            _final_response("That would exceed your budget, so I didn't proceed."),
        ]
    )
    with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)):
        result = harness.handle_chat(db_session, "sess-pay-deny", "user_demo", "pay now", 50_000, "req-1")

    assert result.status == "completed"  # DENY feeds back to the model, which then produces a final reply
    trail = harness._audit.get_trail(db_session, "sess-pay-deny")
    denials = [e for e in trail if e.decision == "DENY" and e.rule_name == "SpendCapRule"]
    assert len(denials) == 1

    from app.models.order import Order

    assert db_session.query(Order).count() == 0


def test_retry_after_failure_reuses_razorpay_order_and_leaves_failed_state(db_session):
    """A declined card (or rejected signature) leaves the order FAILED, but
    the same idempotency key must let the user try again — reusing the
    existing Razorpay order rather than creating a second one, and moving
    the status back off FAILED so it doesn't misreport an in-progress retry."""
    seed_pedigree(db_session)
    from app.schemas.cart import CartItemCreate
    from app.services import cart_service

    cart_service.add_item(db_session, "user_demo", CartItemCreate(sku="PET-001", quantity=1))

    confirmed = _propose_and_confirm_payment(db_session, "sess-retry-1", 100_000, "order_rzp_retry1")
    order = order_repo.find_by_razorpay_order_id(db_session, "order_rzp_retry1")
    assert order.status == OrderStatus.AWAITING_CONFIRMATION.value

    # First attempt: tampered signature -> FAILED.
    verify_payment(
        VerifyPaymentRequest(
            razorpay_order_id="order_rzp_retry1", razorpay_payment_id="pay_bad", razorpay_signature="0" * 64
        ),
        _fake_request(),
        _buyer_principal(),
        db_session,
    )
    db_session.refresh(order)
    assert order.status == OrderStatus.FAILED.value

    # Retry: initiate_payment again for the same (unchanged) cart -> same
    # idempotency key -> same order row, same Razorpay order, but back to
    # AWAITING_CONFIRMATION so a fresh payment attempt can succeed.
    from app.orders import service as order_service

    with patch("app.orders.service.gateway.create_order") as mock_create:
        reused = order_service.ensure_razorpay_order(db_session, order)
        mock_create.assert_not_called()  # never a second Razorpay order for the same row

    assert reused.razorpay_order_id == "order_rzp_retry1"
    assert reused.status == OrderStatus.AWAITING_CONFIRMATION.value

    # And the retry can now succeed for real.
    payment_id = "pay_retry_success"
    signature = _sign("order_rzp_retry1", payment_id)
    result = verify_payment(
        VerifyPaymentRequest(razorpay_order_id="order_rzp_retry1", razorpay_payment_id=payment_id, razorpay_signature=signature),
        _fake_request(),
        _buyer_principal(),
        db_session,
    )
    assert result.status == "PAID"
    db_session.refresh(order)
    assert order.status == OrderStatus.PAID.value


def test_test_complete_payment_signs_and_verifies_without_caller_holding_the_secret(db_session):
    """The dev-only /api/payments/test-complete endpoint (Layer 4.5,
    buyer_agent/) — signs a synthetic callback server-side and then runs it
    through the exact same verify_payment() as a real Checkout callback
    would. Only the signing is a shortcut; the real HMAC verification code
    still runs, unmodified."""
    seed_pedigree(db_session)
    from app.schemas.cart import CartItemCreate
    from app.services import cart_service

    cart_service.add_item(db_session, "user_demo", CartItemCreate(sku="PET-001", quantity=1))
    confirmed = _propose_and_confirm_payment(db_session, "sess-test-complete-1", 100_000, "order_test_complete_1")
    assert confirmed.payment is not None

    with patch("app.core.config.settings.app_env", "development"):
        from app.schemas.payments import TestCompletePaymentRequest

        result = complete_test_payment(
            TestCompletePaymentRequest(razorpay_order_id="order_test_complete_1"),
            _fake_request(),
            _buyer_principal(),
            db_session,
        )

    assert result.status == "PAID"
    order = order_repo.find_by_razorpay_order_id(db_session, "order_test_complete_1")
    assert order.status == OrderStatus.PAID.value


def test_test_complete_payment_refused_outside_development():
    from fastapi import HTTPException

    from app.schemas.payments import TestCompletePaymentRequest

    with patch("app.core.config.settings.app_env", "production"):
        try:
            complete_test_payment(
                TestCompletePaymentRequest(razorpay_order_id="whatever"), _fake_request(), _buyer_principal(), None
            )
            assert False, "expected a 404"
        except HTTPException as e:
            assert e.status_code == 404
