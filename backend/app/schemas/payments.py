from pydantic import BaseModel


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentFailedRequest(BaseModel):
    razorpay_order_id: str
    error_code: str | None = None
    error_description: str | None = None


class PaymentResultOut(BaseModel):
    status: str  # "PAID" | "FAILED"
    order_id: int
    razorpay_order_id: str | None
    razorpay_payment_id: str | None = None
    amount_paise: int
    message: str
