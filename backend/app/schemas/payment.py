"""Payment / Stripe schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.models.enums import PaymentStatus
from app.schemas.common import ORMModel


class PaymentOut(ORMModel):
    """Payment record - safe to return, only Stripe ids, never secrets."""

    id: int
    order_id: int
    stripe_session_id: str | None
    stripe_payment_intent_id: str | None
    amount: float
    currency: str
    status: PaymentStatus
    created_at: datetime
    updated_at: datetime


class CheckoutSessionRequest(BaseModel):
    """Optional overrides for the Stripe redirect URLs.

    Amount, currency, user id and order contents are never accepted here - the
    backend derives all of them from the database.
    """

    success_url: HttpUrl | None = None
    cancel_url: HttpUrl | None = None
    customer_email: str | None = None


class CheckoutSessionResponse(BaseModel):
    """Result of creating a Stripe Checkout Session."""

    order_id: int
    session_id: str
    checkout_url: str
    amount: float
    currency: str
    status: str = Field(
        default="PENDING",
        description="Order status. Stays PENDING until the webhook confirms payment.",
    )


class CheckoutStatusResponse(BaseModel):
    """Read-only payment state for an order.

    Never mutates anything - only a verified webhook can change a status.
    """

    order_id: int
    status: str = Field(description="Order status, e.g. PENDING or PAID.")
    payment_status: str = Field(description="Payment status, e.g. PENDING or PAID.")
    session_id: str | None = None
    amount: float
    currency: str
    is_paid: bool


class WebhookResponse(BaseModel):
    """Acknowledgement returned to Stripe for a webhook delivery."""

    received: bool
    status: str = Field(description="processed | duplicate | ignored")
    event_type: str
    event_id: str | None = None
    order_id: int | None = None
