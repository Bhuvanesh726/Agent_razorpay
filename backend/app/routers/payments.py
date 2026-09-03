"""Payment completion — driven by the browser's Razorpay Checkout callback,
not by the agent chat loop. This is deliberately outside the harness: the
actual card entry happens inside Razorpay's own hosted UI, asynchronously,
so there is no single Python call that can "return" a payment result the
way other tools do.

Signature verification is what decides success here — never the frontend's
say-so. See app/payments/gateway.py.
"""

import hashlib
import hmac
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.auth.deps import get_principal
from app.auth.principal import Principal
from app.auth.routing import AuthRequirement, SecureAPIRoute, requires
from app.core.config import settings
from app.database import get_db
from app.orders import repository as order_repo
from app.orders import service as order_service
from app.orders.state_machine import OrderStatus
from app.payments.gateway import gateway
from app.schemas.payments import PaymentFailedRequest, PaymentResultOut, TestCompletePaymentRequest, VerifyPaymentRequest

router = APIRouter(tags=["payments"], route_class=SecureAPIRoute)
_audit = AuditService()


def _find_owned_order(db: Session, razorpay_order_id: str, principal: Principal):
    order = order_repo.find_by_razorpay_order_id(db, razorpay_order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="No order found for this razorpay_order_id.")
    if order.user_id != principal.user_id:
        # Identical 404 whether the order doesn't exist or isn't the
        # caller's — a 403 here would confirm to a prober that the
        # razorpay_order_id is real.
        raise HTTPException(status_code=404, detail="No order found for this razorpay_order_id.")
    return order


@router.post("/api/payments/verify", response_model=PaymentResultOut)
@requires(AuthRequirement.BUYER)
def verify_payment(
    payload: VerifyPaymentRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> PaymentResultOut:
    request_id = getattr(request.state, "request_id", None)

    order = _find_owned_order(db, payload.razorpay_order_id, principal)

    # Idempotent: a duplicate verify call for an order that's already PAID
    # (rapid double-click, a retried request) is reported back as the same
    # success — never re-processed, never a second Payment row.
    if OrderStatus(order.status) == OrderStatus.PAID:
        _audit.log_event(
            db,
            session_id=order.session_id,
            user_id=order.user_id,
            event_type="duplicate_payment_prevented",
            actor="system",
            decision="DENY",
            tool_args={"razorpay_order_id": payload.razorpay_order_id, "razorpay_payment_id": payload.razorpay_payment_id},
            reason=f"Order {order.id} is already PAID — ignoring a repeat verify call instead of "
            "processing it as a new payment.",
            request_id=request_id,
        )
        existing_payment_id = order.payments[-1].razorpay_payment_id if order.payments else None
        return PaymentResultOut(
            status="PAID",
            order_id=order.id,
            razorpay_order_id=order.razorpay_order_id,
            razorpay_payment_id=existing_payment_id,
            amount_paise=order.amount_paise,
            message="This order was already paid — no second charge was made.",
        )

    is_valid = gateway.verify_signature(
        payload.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature
    )

    if not is_valid:
        _audit.log_event(
            db,
            session_id=order.session_id,
            user_id=order.user_id,
            event_type="signature_rejected",
            actor="system",
            decision="DENY",
            tool_args={"razorpay_order_id": payload.razorpay_order_id, "razorpay_payment_id": payload.razorpay_payment_id},
            reason="HMAC signature verification failed — refusing to mark this order paid.",
            request_id=request_id,
        )
        order_service.mark_failed(
            db,
            order,
            error_code="signature_verification_failed",
            error_description="Razorpay signature did not match.",
            razorpay_payment_id=payload.razorpay_payment_id,
        )
        return PaymentResultOut(
            status="FAILED",
            order_id=order.id,
            razorpay_order_id=order.razorpay_order_id,
            razorpay_payment_id=payload.razorpay_payment_id,
            amount_paise=order.amount_paise,
            message="Payment signature could not be verified.",
        )

    _audit.log_event(
        db,
        session_id=order.session_id,
        user_id=order.user_id,
        event_type="signature_verified",
        actor="system",
        decision="ALLOW",
        tool_args={"razorpay_order_id": payload.razorpay_order_id, "razorpay_payment_id": payload.razorpay_payment_id},
        reason="HMAC signature verified successfully.",
        request_id=request_id,
    )

    order_service.mark_paid(
        db,
        order,
        razorpay_payment_id=payload.razorpay_payment_id,
        method=None,
        raw_response={"razorpay_order_id": payload.razorpay_order_id, "razorpay_payment_id": payload.razorpay_payment_id},
    )
    _audit.log_event(
        db,
        session_id=order.session_id,
        user_id=order.user_id,
        event_type="payment_succeeded",
        actor="system",
        tool_args={"razorpay_payment_id": payload.razorpay_payment_id},
        reason=f"Payment {payload.razorpay_payment_id} captured for order {order.id}.",
        request_id=request_id,
    )

    return PaymentResultOut(
        status="PAID",
        order_id=order.id,
        razorpay_order_id=order.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        amount_paise=order.amount_paise,
        message="Payment verified and captured.",
    )


@router.post("/api/payments/test-complete", response_model=PaymentResultOut)
@requires(AuthRequirement.BUYER, AuthRequirement.AGENT)
def test_complete_payment(
    payload: TestCompletePaymentRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> PaymentResultOut:
    """Stands in for a completed Razorpay Checkout round-trip in headless
    contexts — same dev-only gating as X-Chaos-Fault (app/testing/chaos.py),
    same reasoning: a genuinely external buyer (buyer_agent/) has no browser
    to drive Checkout's OTP flow and, correctly, no access to this
    merchant's razorpay_key_secret to sign a callback itself. This endpoint
    signs a synthetic payment_id server-side — the secret never leaves this
    process — and then calls the exact same verify_payment() below with it,
    so the real signature-check code path still runs unmodified. Only the
    *signing* is a shortcut; the *verification* is not.

    AGENT is allowed here (unlike /verify and /failed, which stay BUYER-only
    for the real browser-driven Checkout callback) precisely because this
    endpoint exists FOR buyer_agent/ — an external agent has no browser to
    receive that callback in the first place.
    """
    if settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Not found.")

    order = _find_owned_order(db, payload.razorpay_order_id, principal)

    payment_id = f"pay_test_{uuid.uuid4().hex[:12]}"
    signature = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{payload.razorpay_order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    verify_payload = VerifyPaymentRequest(
        razorpay_order_id=payload.razorpay_order_id, razorpay_payment_id=payment_id, razorpay_signature=signature
    )
    return verify_payment(verify_payload, request, principal, db)


@router.post("/api/payments/failed", response_model=PaymentResultOut)
@requires(AuthRequirement.BUYER)
def report_payment_failed(
    payload: PaymentFailedRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> PaymentResultOut:
    """Razorpay's own Checkout reports a failure client-side (e.g. a
    declined test card) with no payment id and nothing to verify — there was
    no successful payment to forge a claim about. This just records it."""
    request_id = getattr(request.state, "request_id", None)

    order = _find_owned_order(db, payload.razorpay_order_id, principal)

    order_service.mark_failed(db, order, error_code=payload.error_code, error_description=payload.error_description)
    _audit.log_event(
        db,
        session_id=order.session_id,
        user_id=order.user_id,
        event_type="payment_failed",
        actor="system",
        tool_args={"error_code": payload.error_code},
        reason=payload.error_description or "Payment failed in Razorpay Checkout.",
        request_id=request_id,
    )

    return PaymentResultOut(
        status="FAILED",
        order_id=order.id,
        razorpay_order_id=order.razorpay_order_id,
        amount_paise=order.amount_paise,
        message=payload.error_description or "Payment failed.",
    )
