"""Order schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import OrderStatus
from app.schemas.common import ORMModel
from app.schemas.payment import PaymentOut


class OrderItemOut(ORMModel):
    """Purchased line, showing the price actually paid at purchase time."""

    id: int
    product_id: int | None
    product_name: str | None = None
    quantity: int
    unit_price: float
    subtotal: float


class OrderOut(ORMModel):
    """Order with its items and payment record."""

    id: int
    user_id: int
    status: OrderStatus
    total_amount: float
    items: list[OrderItemOut] = Field(default_factory=list)
    payment: PaymentOut | None = None
    created_at: datetime
    updated_at: datetime


class OrderStatusUpdate(BaseModel):
    """Admin payload to move an order to another status."""

    status: OrderStatus
    cancel_reason: str | None = Field(default=None, max_length=255)
