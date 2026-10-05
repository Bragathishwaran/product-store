"""Cart schemas.

Every cart response is the *whole* cart (items plus server-calculated totals),
so a client never has to re-fetch after a mutation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

#: Hard ceiling for a single cart line, independent of available stock.
MAX_CART_QUANTITY = 999


class CartItemCreate(BaseModel):
    """Payload to add a product to the cart."""

    product_id: int = Field(gt=0, examples=[1])
    quantity: int = Field(gt=0, le=MAX_CART_QUANTITY, examples=[2])

    model_config = {"json_schema_extra": {"example": {"product_id": 1, "quantity": 2}}}


class CartItemUpdate(BaseModel):
    """Payload to set the quantity of an existing cart line."""

    quantity: int = Field(gt=0, le=MAX_CART_QUANTITY, examples=[3])

    model_config = {"json_schema_extra": {"example": {"quantity": 3}}}


class CartItemOut(BaseModel):
    """A cart line, priced from the live product row."""

    id: int
    product_id: int
    product_name: str
    unit_price: float
    quantity: int
    subtotal: float
    available_stock: int
    in_stock: bool


class CartOut(BaseModel):
    """Full cart with server-calculated totals."""

    id: int
    user_id: int
    items: list[CartItemOut]
    total_items: int = Field(ge=0, default=0)
    total_amount: float = Field(ge=0, default=0.0)
    created_at: datetime
    updated_at: datetime
