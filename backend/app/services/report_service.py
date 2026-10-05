"""SQL reports. All aggregation happens in the database, not in Python."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.user import User
from app.schemas.report import (
    NeverPurchasedProduct,
    ProductSales,
    ProductStock,
    RevenueReport,
    RevenueRow,
    Statistics,
    UserOrderCount,
    UserOrderHistory,
)
from app.utils.money import utcnow

# `paid` is reused by every report so the status filter is defined once.
PAID = Order.status == OrderStatus.PAID


def _day_expression() -> object:
    """Group timestamps by calendar day on supported SQL databases."""
    return func.date(Order.created_at)


def total_revenue(db: Session, days: int | None = None) -> RevenueReport:
    """Report 1 - revenue from paid orders, in total and grouped per day."""
    date_filter = (
        Order.created_at >= (utcnow() - timedelta(days=days)).replace(tzinfo=None)
        if days is not None
        else None
    )
    conditions = [PAID]
    if date_filter is not None:
        conditions.append(date_filter)

    totals = db.execute(
        select(
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
            func.count(Order.id).label("paid_orders"),
        ).where(*conditions)
    ).one()

    revenue = float(totals.revenue or 0)
    paid_count = int(totals.paid_orders or 0)

    daily_rows = db.execute(
        select(
            _day_expression().label("day"),
            func.count(Order.id).label("paid_orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(*conditions)
        .group_by(_day_expression())
        .order_by(_day_expression())
    ).all()

    return RevenueReport(
        currency=settings.STRIPE_CURRENCY,
        total_revenue=round(revenue, 2),
        total_paid_orders=paid_count,
        average_order_value=round(revenue / paid_count, 2) if paid_count else 0.0,
        daily=[
            RevenueRow(
                day=str(row.day),
                paid_orders=int(row.paid_orders),
                revenue=round(float(row.revenue or 0), 2),
            )
            for row in daily_rows
        ],
    )


def revenue_by_day(db: Session, days: int = 30) -> RevenueReport:
    """Revenue totals and daily breakdown over the requested recent window."""
    return total_revenue(db, days=days)


def most_purchased_products(db: Session, limit: int = 10) -> list[ProductSales]:
    """Report 2 - best sellers by quantity across paid orders."""
    stmt = (
        select(
            OrderItem.product_id,
            func.max(Product.name).label("name"),
            func.sum(OrderItem.quantity).label("total_quantity"),
            func.coalesce(func.sum(OrderItem.subtotal), 0).label("revenue"),
            func.count(func.distinct(OrderItem.order_id)).label("order_count"),
        )
        .join(Product, Product.id == OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(PAID)
        .group_by(OrderItem.product_id)
        .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.product_id.asc())
        .limit(limit)
    )

    return [
        ProductSales(
            product_id=int(row.product_id),
            name=str(row.name),
            product_name=str(row.name),
            total_quantity=int(row.total_quantity or 0),
            revenue=round(float(row.revenue or 0), 2),
            order_count=int(row.order_count or 0),
        )
        for row in db.execute(stmt).all()
    ]


def orders_per_user(db: Session, limit: int = 100) -> list[UserOrderCount]:
    """Report 3 - order counts and spend per user (outer join, so 0-order users appear)."""
    paid_count = case((PAID, 1), else_=0)

    stmt = (
        select(
            User.id,
            User.name,
            User.email,
            func.count(Order.id).label("total_orders"),
            func.coalesce(func.sum(paid_count), 0).label("paid_orders"),
            func.coalesce(func.sum(cast(Order.total_amount, Float)), 0.0).label("total_spent"),
        )
        .join(Order, Order.user_id == User.id, isouter=True)
        .group_by(User.id, User.name, User.email)
        .order_by(func.count(Order.id).desc(), User.id.asc())
        .limit(limit)
    )

    return [
        UserOrderCount(
            user_id=int(row.id),
            name=str(row.name),
            email=str(row.email),
            total_orders=int(row.total_orders or 0),
            paid_orders=int(row.paid_orders or 0),
            total_spent=round(float(row.total_spent or 0), 2),
        )
        for row in db.execute(stmt).all()
    ]


def products_never_purchased(db: Session) -> list[NeverPurchasedProduct]:
    """Report 4 - active products absent from every paid order (`NOT EXISTS`)."""
    purchased = (
        select(OrderItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.product_id == Product.id, PAID)
        .exists()
    )
    stmt = (
        select(Product.id, Product.name, Product.stock)
        .where(Product.is_active.is_(True), ~purchased)
        .order_by(Product.name.asc(), Product.id.asc())
    )
    return [
        NeverPurchasedProduct(id=int(row.id), name=str(row.name), stock=int(row.stock))
        for row in db.execute(stmt).all()
    ]


def low_stock_products(db: Session, threshold: int = 5) -> list[ProductStock]:
    """Report 5 - active products at or below the low-stock threshold."""
    stmt = (
        select(Product.id, Product.name, Product.stock)
        .where(Product.is_active.is_(True), Product.stock <= threshold)
        .order_by(Product.stock.asc(), Product.id.asc())
    )
    return [
        ProductStock(product_id=int(row.id), name=str(row.name), stock=int(row.stock))
        for row in db.execute(stmt).all()
    ]


def user_order_history(db: Session, user_id: int) -> UserOrderHistory:
    """Report 6 - a user's order history with its line items."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found."
        )

    orders = (
        db.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
        )
        .scalars()
        .all()
    )

    return UserOrderHistory(
        user_id=user.id,
        name=user.name,
        email=user.email,
        order_count=len(orders),
        orders=orders,
    )


def statistics(db: Session) -> Statistics:
    """Dashboard counters for ``GET /admin/statistics``."""

    def count(model: type, *conditions: object) -> int:
        stmt = select(func.count(model.id))
        if conditions:
            stmt = stmt.where(*conditions)
        return int(db.execute(stmt).scalar_one())

    revenue = db.execute(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(PAID)
    ).scalar_one()

    return Statistics(
        total_products=count(Product),
        active_products=count(Product, Product.is_active.is_(True)),
        total_users=count(User),
        total_orders=count(Order),
        paid_orders=count(Order, PAID),
        pending_orders=count(Order, Order.status == OrderStatus.PENDING),
        failed_orders=count(Order, Order.status == OrderStatus.FAILED),
        cancelled_orders=count(Order, Order.status == OrderStatus.CANCELLED),
        total_revenue=round(float(revenue or 0), 2),
        currency=settings.STRIPE_CURRENCY,
    )


__all__ = [
    "Decimal",
    "date",
    "low_stock_products",
    "most_purchased_products",
    "orders_per_user",
    "products_never_purchased",
    "revenue_by_day",
    "statistics",
    "total_revenue",
    "user_order_history",
]
