"""OrderItem model: price snapshot of a product at purchase time."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.order import Order
    from app.models.product import Product


class OrderItem(Base):
    """A purchased product line.

    `unit_price` and `subtotal` are snapshots taken at checkout, so historical
    orders keep showing the price that was actually paid even if the product
    price changes later. `product_id` is nullable (ON DELETE SET NULL) so
    removing a product never breaks an existing order.
    """

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True, nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped[Optional["Order"]] = relationship(back_populates="items")
    product: Mapped[Optional["Product"]] = relationship(back_populates="order_items")

    @property
    def product_name(self) -> str | None:
        """Live product name for rendering (the price stays the snapshot above)."""
        return self.product.name if self.product is not None else None

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price_non_negative"),
        CheckConstraint("subtotal >= 0", name="ck_order_items_subtotal_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<OrderItem id={self.id} product_id={self.product_id} qty={self.quantity}>"
