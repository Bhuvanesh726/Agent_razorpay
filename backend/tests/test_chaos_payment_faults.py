"""Payment-side chaos faults: FAIL_PAYMENT, RAZORPAY_TIMEOUT, DB_CONFLICT,
TAMPERED_SIGNATURE. Each asserts the system reaches the correct terminal
state and writes the correct audit entry — no network access needed;
RAZORPAY_TIMEOUT/FAIL_PAYMENT/TAMPERED_SIGNATURE never reach the real
Razorpay API at all when the fault fires, and DB_CONFLICT exercises the
real UNIQUE-constraint recovery path against a real (self-injected) row.
"""

import hashlib
import hmac
import json
from unittest.mock import patch

from app.agent import harness
from app.core.config import settings
from app.llm.gateway import GatewayResult
from app.llm.gateway import ToolCall as GatewayToolCall
from app.orders import repository as order_repo
from app.orders.state_machine import OrderStatus
from app.payments.gateway import PaymentGatewayError, RazorpayOrder, gateway as payment_gateway
from app.repositories import product_repo
from app.routers.payments import verify_payment
from app.schemas.payments import VerifyPaymentRequest


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


def _chaos_dev():
    return patch("app.testing.chaos.settings.app_env", "development")


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


def _propose_and_confirm(db, session_id, budget_paise, razorpay_order_id):
    scripted = iter([_tool_call_response("initiate_payment", {})])
    with (
        patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted)),
        patch(
            "app.orders.service.gateway.create_order",
            return_value=RazorpayOrder(razorpay_order_id=razorpay_order_id, amount_paise=74000, currency="INR", receipt="r"),
        ),
    ):
        proposal = harness.handle_chat(db, session_id, "user_demo", "pay for my cart", budget_paise, "req-1")
        assert proposal.status == "awaiting_confirmation"

        scripted_after = iter([_final_response("ok")])
        with patch("app.agent.harness.gateway.call", side_effect=lambda *a, **k: next(scripted_after)):
            return harness.handle_confirm(db, session_id, "user_demo", True, "req-2")


def test_fail_payment_declines_and_preserves_cart(db_session):
    seed_pedigree(db_session)
    from app.repositories import cart_repo
    from app.schemas.cart import CartItemCreate
    from app.services import cart_service

    cart_service.add_item(db_session, "user_demo", CartItemCreate(sku="PET-001", quantity=1))

    with _chaos_dev(), patch("app.testing.chaos.settings.chaos_fault", "FAIL_PAYMENT"):
        confirmed = _propose_and_confirm(db_session, "sess-fail-payment", 100_000, "order_chaos_fail1")

    assert confirmed.payment is None

    order = order_repo.find_by_razorpay_order_id(db_session, "order_chaos_fail1")
    assert order.status == OrderStatus.FAILED.value
    assert order.payments[-1].error_code == "chaos_injected_decline"

    # cart intact — nothing was cleared, no phantom charge
    cart = cart_repo.get_or_create_active_cart(db_session, "user_demo")
    assert len(cart.items) == 1

    trail = harness._audit.get_trail(db_session, "sess-fail-payment")
    assert any(e.event_type == "chaos_fault_injected" for e in trail)
    assert any(e.event_type == "payment_failed" for e in trail)


def test_razorpay_timeout_raises_server_error_without_network(db_session):
    with _chaos_dev(), patch("app.testing.chaos.settings.chaos_fault", "RAZORPAY_TIMEOUT"):
        try:
            payment_gateway.create_order(1000, "INR", "receipt-chaos")
            assert False, "expected PaymentGatewayError"
        except PaymentGatewayError as e:
            assert e.category == "server_error"
            assert "timeout" in str(e).lower() or "hung" in str(e).lower()


def test_razorpay_timeout_fails_the_order_via_ensure_razorpay_order(db_session):
    from app.orders import service as order_service
    from app.orders.repository import get_or_create

    order, _created = get_or_create(
        db_session,
        idempotency_key="chaos-timeout-key",
        user_id="user_demo",
        session_id="sess-x",
        cart_id=1,
        amount_paise=1000,
        currency="INR",
    )
    with _chaos_dev(), patch("app.testing.chaos.settings.chaos_fault", "RAZORPAY_TIMEOUT"):
        try:
            order_service.ensure_razorpay_order(db_session, order)
            assert False, "expected PaymentGatewayError"
        except PaymentGatewayError:
            pass
    db_session.refresh(order)
    assert order.status == OrderStatus.FAILED.value


def test_db_conflict_recovers_via_real_unique_constraint(db_session):
    """Injects a genuinely competing row (via a separate session/transaction)
    right before our own insert, so the existing IntegrityError-recovery path
    in get_or_create runs for real — same mechanism proven generically in
    test_order_repository_concurrency.py, triggered deterministically here."""
    with _chaos_dev(), patch("app.testing.chaos.settings.chaos_fault", "DB_CONFLICT"):
        order, created = order_repo.get_or_create(
            db_session,
            idempotency_key="chaos-conflict-key",
            user_id="user_demo",
            session_id="sess-conflict",
            cart_id=1,
            amount_paise=5000,
            currency="INR",
        )

    assert created is False  # our insert lost the race to the injected one
    assert order.idempotency_key == "chaos-conflict-key"

    count = db_session.query(order_repo.Order).filter_by(idempotency_key="chaos-conflict-key").count()
    assert count == 1


def test_tampered_signature_rejects_even_a_correctly_computed_signature(db_session):
    seed_pedigree(db_session)
    from app.schemas.cart import CartItemCreate
    from app.services import cart_service
    import types

    cart_service.add_item(db_session, "user_demo", CartItemCreate(sku="PET-001", quantity=1))

    with _chaos_dev(), patch("app.testing.chaos.settings.chaos_fault", "TAMPERED_SIGNATURE"):
        confirmed = _propose_and_confirm(db_session, "sess-tampered-sig", 100_000, "order_chaos_sig1")
    assert confirmed.payment is not None

    payment_id = "pay_chaos_sig1"
    message = f"order_chaos_sig1|{payment_id}"
    real_signature = hmac.new(settings.razorpay_key_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    with _chaos_dev(), patch("app.testing.chaos.settings.chaos_fault", "TAMPERED_SIGNATURE"):
        result = verify_payment(
            VerifyPaymentRequest(razorpay_order_id="order_chaos_sig1", razorpay_payment_id=payment_id, razorpay_signature=real_signature),
            types.SimpleNamespace(state=types.SimpleNamespace()),
            db_session,
        )

    assert result.status == "FAILED"
    order = order_repo.find_by_razorpay_order_id(db_session, "order_chaos_sig1")
    assert order.status == OrderStatus.FAILED.value

    trail = harness._audit.get_trail(db_session, "sess-tampered-sig")
    assert any(e.event_type == "signature_rejected" and e.decision == "DENY" for e in trail)
