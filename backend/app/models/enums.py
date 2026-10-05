"""Shared status enumerations for orders and payments."""

from __future__ import annotations

import enum


class OrderStatus(str, enum.Enum):
    """Lifecycle of an order.

    PENDING   -> order created, awaiting payment confirmation from Stripe
    PAID      -> payment confirmed by the Stripe webhook, stock deducted
    FAILED    -> payment failed
    CANCELLED -> checkout expired or cancelled by the user/admin
    """

    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, enum.Enum):
    """Lifecycle of a payment (mirrors the order status by design)."""

    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: Statuses after which an order/payment is considered final.
FINAL_STATUSES = {
    OrderStatus.PAID,
    OrderStatus.FAILED,
    OrderStatus.CANCELLED,
}
