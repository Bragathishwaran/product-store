"""Stripe payment service: Checkout Sessions and webhook processing.

The frontend never decides whether an order is paid - that transition only
happens here, driven by a signature-verified Stripe webhook.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.order import Order
from app.models.payment import Payment
from app.models.stripe_event import StripeEvent
from app.models.user import User
from app.schemas.payment import CheckoutSessionResponse
from app.services import order_service
from app.utils.money import to_float, to_minor_units
from app.utils.stripe_objects import obj_get

logger = logging.getLogger(__name__)

#: Events that mean "the buyer paid".
PAID_EVENTS = {
    "checkout.session.async_payment_succeeded",
    "payment_intent.succeeded",
}
#: Events that mean "the payment failed".
FAILED_EVENTS = {
    "payment_intent.payment_failed",
    "checkout.session.async_payment_failed",
}
#: Events that mean "checkout was abandoned".
CANCELLED_EVENTS = {"checkout.session.expired"}


# --------------------------------------------------------------------------
# Checkout
# --------------------------------------------------------------------------
def build_line_items(order: Order) -> list[dict[str, Any]]:
    """Build Stripe line items from the order's price snapshots."""
    currency = settings.STRIPE_CURRENCY.lower()
    return [
        {
            "price_data": {
                "currency": currency,
                "unit_amount": to_minor_units(item.unit_price),
                "product_data": {
                    "name": item.product.name if item.product else f"Product {item.product_id}",
                },
            },
            "quantity": item.quantity,
        }
        for item in order.items
    ]


def create_checkout_session(db: Session, user: User) -> CheckoutSessionResponse:
    """Snapshot the cart into an order and open a Stripe Checkout Session."""
    if not settings.stripe_enabled:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stripe is not configured. Set STRIPE_SECRET_KEY in the environment.",
        )

    order = order_service.create_order_from_cart(db, user)

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        stripe_session = stripe.checkout.Session.create(
            mode="payment",
            line_items=build_line_items(order),
            customer_email=user.email,
            client_reference_id=str(order.id),
            success_url=settings.success_url,
            cancel_url=settings.cancel_url,
            metadata={"order_id": str(order.id), "user_id": str(user.id)},
            payment_intent_data={"metadata": {"order_id": str(order.id)}},
            # Retrying an order never creates a second Stripe session.
            idempotency_key=f"order-{order.id}",
        )
    except stripe.StripeError as exc:
        logger.error("Stripe session creation failed for order %s: %s", order.id, exc)
        # Never leave a PENDING order behind that nobody can pay.
        order_service.mark_order_failed(db, order)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment provider is unavailable, please try again.",
        ) from exc

    session_id = obj_get(stripe_session, "id")
    checkout_url = obj_get(stripe_session, "url")
    if not session_id or not checkout_url:  # pragma: no cover - defensive
        logger.error("Stripe returned an incomplete session for order %s", order.id)
        order_service.mark_order_failed(db, order)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment provider returned an invalid session.",
        )

    payment = order.payment
    if payment is not None:
        payment.stripe_session_id = session_id
    db.commit()

    return CheckoutSessionResponse(
        order_id=order.id,
        session_id=session_id,
        checkout_url=checkout_url,
        amount=to_float(order.total_amount),
        currency=settings.STRIPE_CURRENCY.lower(),
        status=order.status.value,
    )


# --------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------
def construct_event(payload: bytes, signature_header: str | None) -> stripe.Event:
    """Verify the Stripe signature and return the parsed event.

    Raises 400 for bad/missing signatures and 500 when no webhook secret is configured.
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("Received a Stripe webhook but STRIPE_WEBHOOK_SECRET is not set")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook secret is not configured.",
        )
    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header",
        )

    try:
        return stripe.Webhook.construct_event(
            payload, signature_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.SignatureVerificationError as exc:
        logger.warning("Rejected Stripe webhook with an invalid signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe webhook signature",
        ) from exc
    except ValueError as exc:  # malformed body or timestamp outside tolerance
        logger.warning("Rejected malformed Stripe webhook: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid Stripe webhook payload: {exc}",
        ) from exc


def _payment_by_session(db: Session, session_id: str | None) -> Payment | None:
    if not session_id:
        return None
    return db.execute(
        select(Payment).where(Payment.stripe_session_id == session_id)
    ).scalar_one_or_none()


def _payment_by_intent(db: Session, intent_id: str | None) -> Payment | None:
    if not intent_id:
        return None
    return db.execute(
        select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
    ).scalar_one_or_none()


def _payment_by_order(db: Session, order_id: int | None) -> Payment | None:
    if order_id is None:
        return None
    return db.execute(select(Payment).where(Payment.order_id == order_id)).scalar_one_or_none()


def _order_id_from_object(data_object: dict[str, Any]) -> int | None:
    """Recover the order id from Stripe metadata or the client reference."""
    candidates = [
        (data_object.get("metadata") or {}).get("order_id"),
        data_object.get("client_reference_id"),
    ]
    for candidate in candidates:
        if candidate in (None, ""):
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            continue
    return None


def _resolve_payment(
    db: Session, data_object: dict[str, Any], intent_id: str | None
) -> Payment | None:
    payment = _payment_by_session(db, data_object.get("id")) or _payment_by_intent(db, intent_id)
    if payment is None:
        payment = _payment_by_order(db, _order_id_from_object(data_object))
    return payment


def _remember_event(db: Session, event: dict[str, Any], order_id: int | None) -> None:
    """Persist the handled event id so redeliveries become no-ops."""
    event_id = event.get("id")
    if not event_id:
        return
    try:
        db.add(
            StripeEvent(
                id=event_id,
                type=event.get("type", "unknown"),
                order_id=order_id,
            )
        )
        db.commit()
    except IntegrityError:  # pragma: no cover - concurrent duplicate delivery
        db.rollback()


def _to_plain_dict(value: Any) -> Any:
    """Convert Stripe objects recursively before treating them as mappings."""
    if isinstance(value, dict):
        return {key: _to_plain_dict(item) for key, item in value.items()}
    if hasattr(value, "to_dict_recursive"):
        return value.to_dict_recursive()
    if hasattr(value, "to_dict"):
        return _to_plain_dict(value.to_dict())
    return value


def process_event(db: Session, event: stripe.Event) -> dict[str, Any]:
    """Apply a verified Stripe event to the order/payment records.

    Idempotent: the event id is stored in `stripe_events`, so a redelivered
    event is reported as `duplicate` and changes nothing.
    """
    event = _to_plain_dict(event)
    event_id = event.get("id")
    event_type = event.get("type", "")
    data_object = (event.get("data") or {}).get("object") or {}

    if event_id:
        previous = db.get(StripeEvent, event_id)
        if previous is not None:
            logger.info("Stripe event %s already processed - ignoring", event_id)
            return {
                "received": True,
                "status": "duplicate",
                "event_type": event_type,
                "event_id": event_id,
                "order_id": previous.order_id,
            }

    intent_id = data_object.get("payment_intent") or (
        data_object.get("id") if event_type.startswith("payment_intent.") else None
    )
    payment = _resolve_payment(db, data_object, intent_id)

    if payment is None:
        logger.warning("No order found for Stripe event %s (%s)", event_id, event_type)
        _remember_event(db, event, None)
        return {
            "received": True,
            "status": "ignored",
            "event_type": event_type,
            "event_id": event_id,
            "order_id": None,
        }

    order = payment.order
    if payment.stripe_payment_intent_id is None and intent_id:
        payment.stripe_payment_intent_id = intent_id

    outcome = "ignored"
    if event_type == "checkout.session.completed":
        if data_object.get("payment_status") == "paid":
            changed = order_service.mark_order_paid(db, order, intent_id)
            outcome = "processed" if changed else "duplicate"
    elif event_type in PAID_EVENTS:
        changed = order_service.mark_order_paid(db, order, intent_id)
        outcome = "processed" if changed else "duplicate"
    elif event_type in FAILED_EVENTS:
        outcome = "processed" if order_service.mark_order_failed(db, order) else "duplicate"
    elif event_type in CANCELLED_EVENTS:
        outcome = "processed" if order_service.mark_order_cancelled(db, order) else "duplicate"

    _remember_event(db, event, order.id)
    db.commit()
    db.refresh(order)
    db.refresh(payment)
    logger.info(
        "Processed Stripe event %s (%s) for order %s: %s",
        event_id,
        event_type,
        order.id,
        outcome,
    )

    return {
        "received": True,
        "status": outcome,
        "event_type": event_type,
        "event_id": event_id,
        "order_id": order.id,
    }
