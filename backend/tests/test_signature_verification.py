"""Signature verification is pure HMAC computation — no network call, so
this runs fully offline against the real gateway instance (constructed from
whatever RAZORPAY_KEY_SECRET is configured for this environment).
"""

import hashlib
import hmac

from app.core.config import settings
from app.payments.gateway import gateway


def _sign(order_id: str, payment_id: str, secret: str) -> str:
    message = f"{order_id}|{payment_id}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def test_valid_signature_is_accepted():
    order_id, payment_id = "order_test123", "pay_test456"
    signature = _sign(order_id, payment_id, settings.razorpay_key_secret)
    assert gateway.verify_signature(order_id, payment_id, signature) is True


def test_tampered_signature_is_rejected():
    order_id, payment_id = "order_test123", "pay_test456"
    valid_signature = _sign(order_id, payment_id, settings.razorpay_key_secret)
    tampered = valid_signature[:-4] + ("0000" if valid_signature[-4:] != "0000" else "1111")
    assert gateway.verify_signature(order_id, payment_id, tampered) is False


def test_signature_for_different_payment_id_is_rejected():
    """A signature valid for one payment must not verify for a different one
    — this is what stops someone replaying a real signature against a
    different (unpaid) order/payment pair."""
    order_id = "order_test123"
    signature_for_pay_1 = _sign(order_id, "pay_test111", settings.razorpay_key_secret)
    assert gateway.verify_signature(order_id, "pay_test222", signature_for_pay_1) is False


def test_signature_with_wrong_secret_is_rejected():
    order_id, payment_id = "order_test123", "pay_test456"
    wrong_secret_signature = _sign(order_id, payment_id, "not-the-real-secret")
    assert gateway.verify_signature(order_id, payment_id, wrong_secret_signature) is False


def test_malformed_signature_does_not_raise():
    assert gateway.verify_signature("order_test123", "pay_test456", "") is False
    assert gateway.verify_signature("order_test123", "pay_test456", "not-hex-at-all!!") is False
