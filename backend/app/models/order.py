from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.orders.state_machine import OrderStatus


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id"), nullable=False)

    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=OrderStatus.PENDING.value)

    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # The idempotency guarantee lives here: a real UNIQUE constraint, not an
    # application-level check. See app/orders/repository.py for how a
    # conflicting insert is handled (insert, catch IntegrityError, re-select
    # the winner — never "check then insert").
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    payments: Mapped[list["Payment"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)

    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)  # "captured" | "failed"
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str | None] = mapped_column(String(30), nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The raw Razorpay API/webhook payload for this attempt — useful for
    # debugging, never contains the key secret or a full card number (Razorpay
    # itself never returns those).
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)

    order: Mapped["Order"] = relationship(back_populates="payments")
