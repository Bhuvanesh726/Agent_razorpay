"""Payment completion — driven by the browser's Razorpay Checkout callback,
not by the agent chat loop. This is deliberately outside the harness: the
actual card entry happens inside Razorpay's own hosted UI, asynchronously,
so there is no single Python call that can "return" a payment result the
way other tools do.

Signature verification is what decides success here — never the frontend's
say-so. See app/payments/gateway.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.database import get_db
from app.orders import repository as order_repo
from app.orders import service as order_service
from app.orders.state_machine import OrderStatus
from app.payments.gateway import gateway
from app.schemas.payments import PaymentFailedRequest, PaymentResultOut, VerifyPaymentRequest

router = APIRouter(tags=["payments"])
_audit = AuditService()


@router.post("/api/payments/verify", response_model=PaymentResultOut)
def verify_payment(payload: VerifyPaymentRequest, request: Request, db: Session = Depends(get_db)) -> PaymentResultOut:
    request_id = getattr(request.state, "request_id", None)

    order = order_repo.find_by_razorpay_order_id(db, payload.razorpay_order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="No order found for this razorpay_order_id.")

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


@router.post("/api/payments/failed", response_model=PaymentResultOut)
def report_payment_failed(
    payload: PaymentFailedRequest, request: Request, db: Session = Depends(get_db)
) -> PaymentResultOut:
    """Razorpay's own Checkout reports a failure client-side (e.g. a
    declined test card) with no payment id and nothing to verify — there was
    no successful payment to forge a claim about. This just records it."""
    request_id = getattr(request.state, "request_id", None)

    order = order_repo.find_by_razorpay_order_id(db, payload.razorpay_order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="No order found for this razorpay_order_id.")

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
