"""The single choke point for the Razorpay SDK. Nothing else in the codebase
imports `razorpay` directly.

Test mode only — driven by whatever RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET are
configured. The secret never leaves this module: it's used to construct the
SDK client and to verify signatures, and is never included in any return
value, log line, or exception message.
"""

from dataclasses import dataclass

import razorpay
from razorpay.errors import BadRequestError, GatewayError as RazorpaySDKGatewayError, ServerError

from app.core.config import settings
from app.core.logging import logger


class PaymentGatewayError(Exception):
    """category: 'client_error' (bad request — not retryable) |
    'server_error' (Razorpay-side or network failure — safe to retry/fail the
    order) """

    def __init__(self, message: str, category: str):
        super().__init__(message)
        self.category = category


@dataclass
class RazorpayOrder:
    razorpay_order_id: str
    amount_paise: int
    currency: str
    receipt: str | None


class RazorpayGateway:
    def __init__(self, key_id: str, key_secret: str):
        self._key_id = key_id
        self._client = razorpay.Client(auth=(key_id, key_secret))

    @property
    def public_key_id(self) -> str:
        """Safe to send to the frontend — this is the publishable id, not the secret."""
        return self._key_id

    def create_order(self, amount_paise: int, currency: str, receipt: str) -> RazorpayOrder:
        try:
            response = self._client.order.create(
                {
                    "amount": amount_paise,
                    "currency": currency,
                    "receipt": receipt,
                    "payment_capture": 1,
                }
            )
        except BadRequestError as e:
            logger.error("razorpay order creation rejected", extra={"receipt": receipt, "error": str(e)})
            raise PaymentGatewayError(f"Razorpay rejected the order request: {e}", category="client_error") from e
        except (ServerError, RazorpaySDKGatewayError) as e:
            logger.error("razorpay order creation failed (server-side)", extra={"receipt": receipt, "error": str(e)})
            raise PaymentGatewayError(f"Razorpay server error: {e}", category="server_error") from e
        except Exception as e:
            logger.error("razorpay order creation failed (network/unexpected)", extra={"receipt": receipt, "error": str(e)})
            raise PaymentGatewayError(f"Could not reach Razorpay: {e}", category="server_error") from e

        return RazorpayOrder(
            razorpay_order_id=response["id"],
            amount_paise=response["amount"],
            currency=response["currency"],
            receipt=response.get("receipt"),
        )

    def verify_signature(self, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> bool:
        """Never trust a frontend claim of success — this HMAC check is what
        actually decides. Returns False on any mismatch or malformed input;
        never raises."""
        try:
            self._client.utility.verify_payment_signature(
                {
                    "razorpay_order_id": razorpay_order_id,
                    "razorpay_payment_id": razorpay_payment_id,
                    "razorpay_signature": razorpay_signature,
                }
            )
            return True
        except razorpay.errors.SignatureVerificationError:
            return False
        except Exception as e:
            logger.error("signature verification raised unexpectedly", extra={"error": str(e)})
            return False


gateway = RazorpayGateway(key_id=settings.razorpay_key_id, key_secret=settings.razorpay_key_secret)
