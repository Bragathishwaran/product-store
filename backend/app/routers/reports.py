"""SQL report routes (admin only).

Every endpoint is backed by a real SQL aggregate (`GROUP BY`, `JOIN`,
`NOT IN`) rather than Python-side counting.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.dependencies import CurrentAdmin, DbSession
from app.schemas.common import ErrorResponse
from app.schemas.report import (
    NeverPurchasedProduct,
    ProductSales,
    ProductStock,
    RevenueReport,
    UserOrderCount,
    UserOrderHistory,
)
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])

FORBIDDEN = {403: {"model": ErrorResponse, "description": "Admin privileges required"}}
ADMIN_ONLY = " Admin only - non-admins receive **403 Forbidden**."


@router.get(
    "/revenue",
    response_model=RevenueReport,
    summary="REPORT: total revenue",
    description=(
        "Revenue from **paid** orders only: a total, the average order value and "
        "a per-day breakdown (`GROUP BY date(created_at)`). Optional `?days=` "
        "window (1-365)." + ADMIN_ONLY
    ),
    responses=FORBIDDEN,
)
def revenue_report(
    db: DbSession,
    _admin: CurrentAdmin,
    days: Annotated[int, Query(ge=1, le=365, description="Days to look back")] = 30,
) -> RevenueReport:
    """Revenue totals plus a per-day series."""
    return report_service.revenue_by_day(db, days=days)


@router.get(
    "/most-purchased-products",
    response_model=list[ProductSales],
    summary="REPORT: most purchased products",
    description=(
        "Products ordered most frequently (`SUM(quantity)` over paid orders), "
        "ranked by quantity sold." + ADMIN_ONLY
    ),
    responses=FORBIDDEN,
)
def most_purchased_products(
    db: DbSession,
    _admin: CurrentAdmin,
    limit: Annotated[int, Query(ge=1, le=100, description="How many products to return")] = 10,
) -> list[ProductSales]:
    """Best sellers by quantity."""
    return report_service.most_purchased_products(db, limit=limit)


@router.get(
    "/orders-per-user",
    response_model=list[UserOrderCount],
    summary="REPORT: number of orders per user",
    description=(
        "Order count and spend per user via `LEFT JOIN orders`, so users "
        "without any order are included too." + ADMIN_ONLY
    ),
    responses=FORBIDDEN,
)
def orders_per_user(db: DbSession, _admin: CurrentAdmin) -> list[UserOrderCount]:
    """Orders and spend per user."""
    return report_service.orders_per_user(db)


@router.get(
    "/products-never-purchased",
    response_model=list[NeverPurchasedProduct],
    summary="REPORT: products never purchased",
    description="Active products that never appeared on a paid order (`NOT IN` subquery)." + ADMIN_ONLY,
    responses=FORBIDDEN,
)
def products_never_purchased(db: DbSession, _admin: CurrentAdmin) -> list[NeverPurchasedProduct]:
    """Products with zero paid orders."""
    return report_service.products_never_purchased(db)


@router.get(
    "/low-stock-products",
    response_model=list[ProductStock],
    summary="REPORT: low stock products",
    description="Active products at or below the stock threshold (default 5)." + ADMIN_ONLY,
    responses=FORBIDDEN,
)
def low_stock_products(
    db: DbSession,
    _admin: CurrentAdmin,
    threshold: Annotated[int, Query(ge=0, le=1_000, description="Stock threshold")] = 5,
) -> list[ProductStock]:
    """Products that need restocking."""
    return report_service.low_stock_products(db, threshold=threshold)


@router.get(
    "/user-order-history/{user_id}",
    response_model=UserOrderHistory,
    summary="REPORT: user order history",
    description="All orders of one user, newest first." + ADMIN_ONLY,
    responses={
        **FORBIDDEN,
        404: {"model": ErrorResponse, "description": "User not found"},
    },
)
def user_order_history(user_id: int, db: DbSession, _admin: CurrentAdmin) -> UserOrderHistory:
    """Full order history of a single user."""
    return report_service.user_order_history(db, user_id)


@router.get(
    "/order-counts-by-status",
    summary="REPORT: order counts grouped by status",
    description="Small SQL aggregation used to sanity-check the dashboards." + ADMIN_ONLY,
    responses=FORBIDDEN,
)
def order_status_summary(db: DbSession, _admin: CurrentAdmin) -> dict[str, int]:
    """Order count per status."""
    return report_service.order_status_counts(db)