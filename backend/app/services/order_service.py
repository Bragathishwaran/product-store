"""Order creation, listing and the payment-completion side effects.

Price is the single most important rule in this module: quantities, unit
prices and the total are always re-read from the database, so a client can
never influence what an order costs.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.cart import Cart
from app.models.cart_item import CartItem
from app.models.enums import OrderStatus, PaymentStatus
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.payment import Payment
from app.models.product import Product
from app.models.user import User
from app.schemas.common import Page, build_page
from app.utils.money import to_decimal
from app.utils.pagination import PaginationParams

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------
def create_order_from_cart(db: Session, user: User) -> Order:
    """Build a ``PENDING`` order from the user's cart.

    The caller owns the transaction because the Stripe API call happens after
    this returns.
    """
    cart = db.execute(select(Cart).where(Cart.user_id == user.id)).scalar_one_or_none()
    if cart is None or not cart.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot start checkout: your cart is empty.",
        )

    lines: list[tuple[Product, int, Decimal]] = []
    total = Decimal("0.00")

    for item in cart.items:
        # Re-read the product row and re-validate everything at checkout time.
        product = db.get(Product, item.product_id)
        if product is None or not product.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Product {item.product_id} is no longer available. "
                    "Please remove it from your cart."
                ),
            )
        if item.quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid quantity for product {product.id}.",
            )
        if product.stock < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Only {product.stock} unit(s) of '{product.name}' left in stock. "
                    "Please update your cart."
                ),
            )

        # Snapshot the price now; the order stays correct if the product is
        # repriced or deactivated later.
        unit_price = to_decimal(product.price)
        total += unit_price * item.quantity
        lines.append((product, item.quantity, unit_price))

    order = Order(user_id=user.id, total_amount=total, status=OrderStatus.PENDING)
    db.add(order)
    db.flush()  # assigns order.id

    for product, quantity, unit_price in lines:
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=quantity,
                unit_price=unit_price,
                subtotal=unit_price * quantity,
            )
        )

    db.add(
        Payment(
            order_id=order.id,
            amount=total,
            currency=settings.STRIPE_CURRENCY,
            status=PaymentStatus.PENDING,
        )
    )
    db.flush()
    return order


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def list_orders(
    db: Session,
    pagination: PaginationParams,
    user_id: int | None = None,
    order_status: OrderStatus | None = None,
) -> Page[Order]:
    """Paginated order listing (one user, or every user when ``user_id`` is None)."""
    stmt = select(Order)
    count_stmt = select(func.count(Order.id)).select_from(Order)

    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
        count_stmt = count_stmt.where(Order.user_id == user_id)
    if order_status is not None:
        stmt = stmt.where(Order.status == order_status)
        count_stmt = count_stmt.where(Order.status == order_status)

    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(Order.created_at.desc(), Order.id.desc())
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
        .scalars()
        .all()
    )
    return build_page(rows, total, pagination.page, pagination.limit)


def get_order(db: Session, order_id: int, user_id: int | None = None) -> Order:
    """Fetch an order, enforcing ownership unless ``user_id`` is None (admin)."""
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Order {order_id} not found."
        )
    if user_id is not None and order.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this order.",
        )
    return order


def get_order_payment(db: Session, order_id: int, user_id: int) -> Payment:
    """Fetch the payment row for an order the caller owns."""
    order = get_order(db, order_id, user_id=user_id)
    payment = order.payment
    if payment is None:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No payment record for order {order_id}.",
        )
    return payment


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------
def deduct_stock_for_order(db: Session, order: Order) -> None:
    """Atomically decrement stock so it can never go negative.

    The conditional ``UPDATE ... WHERE stock >= quantity`` is atomic under
    concurrency and is safe to run repeatedly for the same order.
    """
    for item in order.items:
        result = db.execute(
            update(Product)
            .where(Product.id == item.product_id, Product.stock >= item.quantity)
            .values(stock=Product.stock - item.quantity)
        )
        if result.rowcount == 0:
            # Oversold between checkout and payment: clamp at 0, never negative.
            logger.warning(
                "Order %s: insufficient stock for product %s, clamping to 0",
                order.id,
                item.product_id,
            )
            db.execute(
                update(Product)
                .where(Product.id == item.product_id, Product.stock > 0)
                .values(stock=0)
            )


def restore_stock_for_order(db: Session, order: Order) -> None:
    """Put an order's units back on the shelf (refund / admin cancellation)."""
    for item in order.items:
        db.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .values(stock=Product.stock + item.quantity)
        )


def remove_ordered_items_from_cart(db: Session, order: Order) -> None:
    """Clear only the cart lines this order captured (not items added later)."""
    cart = db.execute(
        select(Cart).where(Cart.user_id == order.user_id)
    ).scalar_one_or_none()
    if cart is None:
        return
    product_ids = [item.product_id for item in order.items]
    if not product_ids:
        return
    db.execute(
        delete(CartItem).where(
            CartItem.cart_id == cart.id, CartItem.product_id.in_(product_ids)
        )
    )


# ---------------------------------------------------------------------------
# Status transitions (driven by the verified webhook, must stay idempotent)
# ---------------------------------------------------------------------------
def mark_order_paid(
    db: Session, order: Order, payment_intent_id: str | None = None
) -> bool:
    """Transition an order to ``PAID`` and run its side effects exactly once."""
    if order.status == OrderStatus.PAID:
        logger.info("Order %s is already paid - skipping duplicate side effects", order.id)
        return False

    order.status = OrderStatus.PAID
    payment = order.payment
    if payment is not None:
        payment.status = PaymentStatus.PAID
        if payment_intent_id:
            payment.stripe_payment_intent_id = payment_intent_id

    deduct_stock_for_order(db, order)
    remove_ordered_items_from_cart(db, order)
    return True


def mark_order_failed(db: Session, order: Order) -> bool:
    """A paid order is never downgraded to FAILED."""
    if order.status in {OrderStatus.PAID, OrderStatus.CANCELLED}:
        return False
    order.status = OrderStatus.FAILED
    if order.payment is not None:
        order.payment.status = PaymentStatus.FAILED
    return True


def mark_order_cancelled(db: Session, order: Order) -> bool:
    """Expiry never overrides a settled payment."""
    if order.status in {OrderStatus.PAID, OrderStatus.FAILED}:
        return False
    order.status = OrderStatus.CANCELLED
    if order.payment is not None:
        order.payment.status = PaymentStatus.CANCELLED
    return True


def admin_set_order_status(
    db: Session, order: Order, new_status: OrderStatus
) -> Order:
    """Manually move an order between states, keeping stock consistent.

    Cancelling a paid order returns its units to stock; doing anything else to
    an already-paid order leaves the deducted stock alone.
    """
    was_paid = order.status == OrderStatus.PAID
    order.status = new_status

    if order.payment is not None:
        order.payment.status = PaymentStatus(new_status.value)

    if was_paid and new_status in {OrderStatus.CANCELLED, OrderStatus.FAILED}:
        restore_stock_for_order(db, order)

    db.commit()
    db.refresh(order)
    return order
