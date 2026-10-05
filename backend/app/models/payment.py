"""Payment model: the Stripe side of an order."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import PaymentStatus
from app.utils.money import utcnow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.order import Order


class Payment(Base):
    """Payment attempt for an order.

    One payment per order (`order_id` unique) and a unique Stripe session id
    make the checkout flow idempotent and prevent duplicate payment rows.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    stripe_session_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), index=True, nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="inr", nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"),
        default=PaymentStatus.PENDING,
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    order: Mapped[Optional["Order"]] = relationship(back_populates="payment")

    __table_args__ = (CheckConstraint("amount >= 0", name="ck_payments_amount_non_negative"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Payment id={self.id} order_id={self.order_id} {self.status}>"
