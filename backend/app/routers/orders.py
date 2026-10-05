"""Order routes. Orders are created by the checkout flow (see payments router)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentUser, DbSession, Pagination
from app.schemas.common import ErrorResponse
from app.schemas.order import OrderOut
from app.schemas.pagination import PageRead
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get(
    "",
    response_model=PageRead[OrderOut],
    summary="List the current user's orders (paginated)",
    description=(
        "Only the authenticated user's orders are returned.\n\n"
        "`GET /orders?page=1&limit=5`\n\n"
        "Each order embeds its items (with the price paid at purchase time) and "
        "its payment status, which is updated from the Stripe webhook."
    ),
    responses={401: {"model": ErrorResponse, "description": "Not authenticated"}},
)
def list_orders(
    pagination: Pagination, current_user: CurrentUser, db: DbSession
) -> PageRead[OrderOut]:
    """Return one page of the user's orders."""
    page = order_service.list_orders(db, pagination, user_id=current_user.id)
    return PageRead[OrderOut](
        items=[OrderOut.model_validate(order) for order in page.items],
        page=page.page,
        limit=page.limit,
        total=page.total,
        total_pages=page.total_pages,
    )


@router.get(
    "/{order_id}",
    response_model=OrderOut,
    summary="Get one of the current user's orders",
    description=(
        "Returns **404 Not Found** for an unknown id and **403 Forbidden** when "
        "the order belongs to another user."
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Not your order"},
        404: {"model": ErrorResponse, "description": "Order not found"},
    },
)
def get_order(order_id: int, current_user: CurrentUser, db: DbSession) -> OrderOut:
    """Fetch a single owned order."""
    order = order_service.get_order(db, order_id, user_id=current_user.id)
    return OrderOut.model_validate(order)
