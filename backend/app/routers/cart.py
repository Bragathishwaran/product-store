"""Cart routes. Every operation is scoped to the authenticated user's cart."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core.dependencies import CurrentUser, DbSession
from app.schemas.cart import CartItemCreate, CartItemUpdate, CartOut
from app.schemas.common import ErrorResponse, Message
from app.services import cart_service

router = APIRouter(prefix="/cart", tags=["Cart"])

ERRORS = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    404: {"model": ErrorResponse, "description": "Cart item not found"},
}


@router.get(
    "",
    response_model=CartOut,
    summary="View the current cart",
    description=(
        "Returns the authenticated user's cart with a **server calculated** "
        "`total_amount` (current product price x quantity). The cart is created "
        "empty on first access."
    ),
    responses=ERRORS,
)
def get_cart(current_user: CurrentUser, db: DbSession) -> CartOut:
    """Return the user's cart."""
    return cart_service.to_schema(cart_service.get_cart(db, current_user))


@router.post(
    "/items",
    response_model=CartOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a product to the cart",
    description=(
        "Adds a product, or increments the quantity when the product is already "
        "in the cart. Rejects unknown/inactive products and quantities above the "
        "available stock with **400 Bad Request**."
    ),
    responses={
        **ERRORS,
        400: {"model": ErrorResponse, "description": "Invalid quantity or insufficient stock"},
        422: {"description": "Invalid payload"},
    },
)
def add_cart_item(payload: CartItemCreate, current_user: CurrentUser, db: DbSession) -> CartOut:
    """Add (or increment) a cart line and return the updated cart."""
    cart = cart_service.add_item(db, current_user, payload.product_id, payload.quantity)
    return cart_service.to_schema(cart)


@router.put(
    "/items/{item_id}",
    response_model=CartOut,
    summary="Update a cart item quantity",
    description="Sets the quantity of a cart line. Returns **404** for another user's item.",
    responses={
        **ERRORS,
        400: {"model": ErrorResponse, "description": "Invalid quantity or insufficient stock"},
    },
)
def update_cart_item(
    item_id: int,
    payload: CartItemUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> CartOut:
    """Replace the quantity of one cart line."""
    cart = cart_service.update_item(db, current_user, item_id, payload.quantity)
    return cart_service.to_schema(cart)


@router.delete(
    "/items/{item_id}",
    response_model=CartOut,
    summary="Remove a cart item",
    description="Removes one line from the authenticated user's cart.",
    responses=ERRORS,
)
def remove_cart_item(item_id: int, current_user: CurrentUser, db: DbSession) -> CartOut:
    """Delete a single cart line."""
    cart = cart_service.remove_item(db, current_user, item_id)
    return cart_service.to_schema(cart)


@router.delete(
    "",
    response_model=CartOut,
    summary="Empty the cart",
    description="Removes every line from the authenticated user's cart.",
    responses=ERRORS,
)
def clear_cart(current_user: CurrentUser, db: DbSession) -> CartOut:
    """Empty the whole cart."""
    cart = cart_service.clear_cart(db, current_user)
    return cart_service.to_schema(cart)
