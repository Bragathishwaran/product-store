"""StripeEvent model: webhook idempotency ledger.

Stripe retries webhooks until it receives a 2xx. Storing every processed event
id in `stripe_events` guarantees that a redelivered event is a no-op: no
duplicate orders, no duplicate payment rows and no second stock deduction.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.money import utcnow


class StripeEvent(Base):
    """A Stripe webhook event that has already been handled."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<StripeEvent id={self.id!r} type={self.type}>"
