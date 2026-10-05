"""Payment routes: Stripe Checkout Session creation and webhook handling."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from app.core.dependencies import CurrentUser, DbSession
from app.models.payment import Payment
from app.schemas.common import ErrorResponse
from app.schemas.order import OrderOut
from app.schemas.payment import CheckoutSessionResponse, PaymentOut, WebhookResponse
from app.services import order_service, payment_service

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "/create-checkout-session",
    response_model=CheckoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start Stripe Checkout for the current cart",
    description=(
        "Converts the user's cart into a `PENDING` order (order items, a payment "
        "record and a server-calculated total) and returns a Stripe Checkout "
        "Session URL.\n\n"
        "Amount, user id and payment status always come from the database - the "
        "frontend cannot influence them.\n\n"
        "Returns **400** when the cart is empty."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Empty cart or insufficient stock"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        500: {"model": ErrorResponse, "description": "Stripe not configured / provider error"},
    },
)
def create_checkout_session(current_user: CurrentUser, db: DbSession) -> CheckoutSessionResponse:
    """Create the order and the Stripe Checkout Session."""
    return payment_service.create_checkout_session(db, current_user)


@router.get(
    "/order/{order_id}",
    response_model=OrderOut,
    summary="Check the payment status of an order",
    description=(
        "Lets the checkout success page poll the authoritative status. The "
        "frontend redirect alone never marks an order as paid - only the Stripe "
        "webhook does."
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Not your order"},
        404: {"model": ErrorResponse, "description": "Order not found"},
    },
)
def get_order_payment_status(order_id: int, current_user: CurrentUser, db: DbSession) -> OrderOut:
    """Return the order with its current payment status."""
    order = order_service.get_order(db, order_id, user_id=current_user.id)
    return OrderOut.model_validate(order)


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    summary="Stripe webhook receiver",
    description=(
        "Public endpoint called by Stripe. The `stripe-signature` header is "
        "verified with `STRIPE_WEBHOOK_SECRET`; invalid or missing signatures "
        "are rejected with **400**.\n\n"
        "Handled events:\n\n"
        "* `checkout.session.completed` with `payment_status=paid` -> order/payment **PAID** (stock deducted)\n"
        "* `checkout.session.async_payment_succeeded` / `payment_intent.succeeded` -> order/payment **PAID**\n"
        "* `checkout.session.completed` with an unpaid session stays **PENDING** until payment succeeds\n"
        "* `checkout.session.expired` -> order/payment **CANCELLED**\n"
        "* `payment_intent.payment_failed` -> order/payment **FAILED**\n\n"
        "Processing is idempotent: a redelivered event id is reported as "
        "`duplicate` and changes nothing."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Invalid payload or signature"},
        500: {"model": ErrorResponse, "description": "Webhook secret not configured"},
    },
)
async def stripe_webhook(request: Request, db: DbSession) -> WebhookResponse:
    """Verify and process a Stripe event (sync DB work runs in a threadpool)."""
    payload = await request.body()
    signature_header = request.headers.get("stripe-signature")

    event = payment_service.construct_event(payload, signature_header)
    result = await run_in_threadpool(payment_service.process_event, db, event)
    return WebhookResponse(**result)


@router.get(
    "/{payment_id}",
    response_model=PaymentOut,
    summary="Get a payment record",
    description="Owner/admin only. Returns the Stripe ids and payment status.",
    responses={
        403: {"model": ErrorResponse, "description": "Not your payment"},
        404: {"model": ErrorResponse, "description": "Payment not found"},
    },
)
def get_payment(payment_id: int, current_user: CurrentUser, db: DbSession) -> PaymentOut:
    """Fetch a payment the caller owns (admins may read any payment)."""
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment {payment_id} not found",
        )
    if not current_user.is_admin and payment.order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this payment",
        )
    return PaymentOut.model_validate(payment)
