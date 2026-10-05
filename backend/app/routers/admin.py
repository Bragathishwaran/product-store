"""Admin routes. Every endpoint here requires an admin token (**403** otherwise)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentAdmin, DbSession, Pagination
from app.models.enums import OrderStatus
from app.schemas.common import ErrorResponse
from app.schemas.order import OrderOut, OrderStatusUpdate
from app.schemas.pagination import PageRead
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate
from app.schemas.report import Statistics
from app.schemas.user import UserOut
from app.services import auth_service, order_service, product_service, report_service

router = APIRouter(prefix="/admin", tags=["Admin"])

FORBIDDEN = {403: {"model": ErrorResponse, "description": "Admin privileges required"}}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Resource not found"}}
ADMIN_ONLY = " Admin only - non-admins receive **403 Forbidden**."


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------
@router.post(
    "/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
    description="Creates a product." + ADMIN_ONLY,
    responses={**FORBIDDEN, 422: {"description": "Invalid product data"}},
)
def admin_create_product(payload: ProductCreate, db: DbSession, _admin: CurrentAdmin) -> ProductOut:
    """Admin variant of `POST /products`."""
    return ProductOut.model_validate(product_service.create_product(db, payload))


@router.put(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="Update a product",
    description="Partial update of a product." + ADMIN_ONLY,
    responses={**FORBIDDEN, **NOT_FOUND},
)
def admin_update_product(
    product_id: int,
    payload: ProductUpdate,
    db: DbSession,
    _admin: CurrentAdmin,
) -> ProductOut:
    """Admin variant of `PUT /products/{id}`."""
    product = product_service.get_product(db, product_id)
    return ProductOut.model_validate(product_service.update_product(db, product, payload))


@router.delete(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="Delete a product",
    description=(
        "Soft-deletes the product (`is_active = false`) and returns its final "
        "state so existing orders keep their price history." + ADMIN_ONLY
    ),
    responses={**FORBIDDEN, **NOT_FOUND},
)
def admin_delete_product(product_id: int, db: DbSession, _admin: CurrentAdmin) -> ProductOut:
    """Soft-delete a product."""
    product = product_service.delete_product(db, product_service.get_product(db, product_id))
    return ProductOut.model_validate(product)


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------
@router.get(
    "/orders",
    response_model=PageRead[OrderOut],
    summary="List all orders (paginated)",
    description=(
        "Every order of every user, newest first, optionally filtered by "
        "`?status=`." + ADMIN_ONLY
    ),
    responses=FORBIDDEN,
)
def admin_list_orders(
    pagination: Pagination,
    db: DbSession,
    _admin: CurrentAdmin,
    order_status: Annotated[
        OrderStatus | None, Query(alias="status", description="Filter by order status")
    ] = None,
) -> PageRead[OrderOut]:
    """Paginated listing across all users."""
    page = order_service.list_orders(db, pagination, order_status=order_status)
    return PageRead[OrderOut](
        items=[OrderOut.model_validate(order) for order in page.items],
        page=page.page,
        limit=page.limit,
        total=page.total,
        total_pages=page.total_pages,
    )


@router.get(
    "/orders/{order_id}",
    response_model=OrderOut,
    summary="Get any order",
    description="Read any user's order regardless of ownership." + ADMIN_ONLY,
    responses={**FORBIDDEN, **NOT_FOUND},
)
def admin_get_order(order_id: int, db: DbSession, _admin: CurrentAdmin) -> OrderOut:
    """Fetch any order by id."""
    return OrderOut.model_validate(order_service.get_order(db, order_id))


@router.put(
    "/orders/{order_id}/status",
    response_model=OrderOut,
    summary="Change an order status",
    description=(
        "Moves an order between PENDING/PAID/FAILED/CANCELLED. `PAID` deducts "
        "stock; cancelling a paid order restores it." + ADMIN_ONLY
    ),
    responses={**FORBIDDEN, **NOT_FOUND, 422: {"description": "Invalid status"}},
)
def admin_update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: DbSession,
    _admin: CurrentAdmin,
) -> OrderOut:
    """Apply an admin-driven status transition."""
    order = order_service.get_order(db, order_id)
    return OrderOut.model_validate(
        order_service.admin_set_order_status(db, order, payload.status)
    )


# --------------------------------------------------------------------------
# Users + statistics
# --------------------------------------------------------------------------
@router.get(
    "/users",
    response_model=PageRead[UserOut],
    summary="List users (paginated)",
    description="Paginated user directory with optional `?search=` on the name." + ADMIN_ONLY,
    responses=FORBIDDEN,
)
def admin_list_users(
    pagination: Pagination,
    db: DbSession,
    _admin: CurrentAdmin,
    search: Annotated[str | None, Query(max_length=120)] = None,
) -> PageRead[UserOut]:
    """Paginated user directory."""
    page = auth_service.list_users(db, pagination, search=search)
    return PageRead[UserOut](
        items=[UserOut.model_validate(user) for user in page.items],
        page=page.page,
        limit=page.limit,
        total=page.total,
        total_pages=page.total_pages,
    )


@router.get(
    "/statistics",
    response_model=Statistics,
    summary="Dashboard statistics",
    description=(
        "Returns `total_products`, `active_products`, `total_users`, "
        "`total_orders`, the per-status order counts and `total_revenue` "
        "(paid orders only) - all computed with SQL aggregates." + ADMIN_ONLY
    ),
    responses=FORBIDDEN,
)
def admin_statistics(db: DbSession, _admin: CurrentAdmin) -> Statistics:
    """Aggregated dashboard counters."""
    return report_service.statistics(db)