"""Admin dashboard and SQL report schemas.

Every aggregation behind these models is computed by the database (SQL
``SUM`` / ``COUNT`` / ``GROUP BY`` / ``NOT EXISTS``), never in Python.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.order import OrderOut


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class Statistics(BaseModel):
    """Aggregated counters for the admin dashboard."""

    total_products: int = Field(ge=0)
    active_products: int = Field(ge=0)
    total_users: int = Field(ge=0)
    total_orders: int = Field(ge=0)
    paid_orders: int = Field(ge=0)
    pending_orders: int = Field(ge=0)
    failed_orders: int = Field(ge=0)
    cancelled_orders: int = Field(ge=0)
    total_revenue: float = Field(ge=0)
    currency: str


# ---------------------------------------------------------------------------
# Report 1 - revenue
# ---------------------------------------------------------------------------
class RevenueRow(BaseModel):
    """Revenue for a single day."""

    day: str
    paid_orders: int = Field(ge=0)
    revenue: float = Field(ge=0)


class RevenueReport(BaseModel):
    """Revenue from paid orders, in total and grouped per day."""

    currency: str
    total_revenue: float = Field(ge=0)
    total_paid_orders: int = Field(ge=0)
    average_order_value: float = Field(ge=0)
    daily: list[RevenueRow]


# ---------------------------------------------------------------------------
# Report 2 - most purchased products
# ---------------------------------------------------------------------------
class ProductSales(BaseModel):
    """How often a product was purchased."""

    product_id: int
    name: str
    product_name: str
    total_quantity: int = Field(ge=0)
    revenue: float = Field(ge=0)
    order_count: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Report 3 - orders per user
# ---------------------------------------------------------------------------
class UserOrderCount(BaseModel):
    """Order count per user (users without orders are included)."""

    user_id: int
    name: str
    email: str
    total_orders: int = Field(ge=0)
    paid_orders: int = Field(ge=0)
    total_spent: float = Field(ge=0)


# ---------------------------------------------------------------------------
# Report 4 - products never purchased
# ---------------------------------------------------------------------------
class NeverPurchasedProduct(BaseModel):
    """An active product that does not appear on any paid order."""

    id: int
    name: str
    stock: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Report 5 - low stock
# ---------------------------------------------------------------------------
class ProductStock(BaseModel):
    """An active product at or below the low-stock threshold."""

    product_id: int
    name: str
    stock: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Report 6 - user order history
# ---------------------------------------------------------------------------
class UserOrderHistory(BaseModel):
    """A user's complete order history."""

    user_id: int
    name: str
    email: str
    order_count: int = Field(ge=0)
    orders: list[OrderOut]
    generated_at: datetime | None = None
