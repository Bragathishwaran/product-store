"""Product routes: public catalogue + admin-only writes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import CurrentAdmin, DbSession, OptionalUser, Pagination
from app.schemas.common import ErrorResponse, Message
from app.schemas.pagination import PageRead
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate
from app.services import product_service

router = APIRouter(prefix="/products", tags=["Products"])


@router.post(
    "",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product (admin only)",
    description="Only administrators may create products. Regular users get **403 Forbidden**.",
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
        422: {"description": "Invalid product data (price <= 0, negative stock)"},
    },
)
def create_product(payload: ProductCreate, db: DbSession, _admin: CurrentAdmin) -> ProductOut:
    """Create a product."""
    return ProductOut.model_validate(product_service.create_product(db, payload))


@router.get(
    "",
    response_model=PageRead[ProductOut],
    summary="List products (paginated + search)",
    description=(
        "Catalogue endpoint with pagination and search.\n\n"
        "`GET /products?page=1&limit=10&search=python`\n\n"
        "* `page` must be >= 1\n"
        "* `limit` must be between 1 and 100\n"
        "* `search` matches the product name or description (case-insensitive)\n\n"
        "Pagination happens in SQL (`LIMIT`/`OFFSET` plus `COUNT(*)`), so only a "
        "single page is ever loaded into memory. Inactive products are hidden "
        "unless an admin passes `include_inactive=true`."
    ),
    responses={422: {"description": "Invalid pagination parameters"}},
)
def list_products(
    db: DbSession,
    pagination: Pagination,
    current_user: OptionalUser,
    search: Annotated[
        str | None,
        Query(max_length=200, description="Case-insensitive name/description search"),
    ] = None,
    include_inactive: Annotated[bool, Query(description="Admins only")] = False,
) -> PageRead[ProductOut]:
    """Return one page of products."""
    is_admin = bool(current_user and current_user.is_admin)
    if include_inactive and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can list inactive products",
        )

    page = product_service.list_products(
        db, pagination, search=search, include_inactive=include_inactive and is_admin
    )
    return PageRead[ProductOut](
        items=[ProductOut.model_validate(product) for product in page.items],
        page=page.page,
        limit=page.limit,
        total=page.total,
        total_pages=page.total_pages,
    )


@router.get(
    "/{product_id}",
    response_model=ProductOut,
    summary="Get a product by id",
    description="Returns a single product, or **404 Not Found** when it does not exist.",
    responses={404: {"model": ErrorResponse, "description": "Product not found"}},
)
def get_product(
    product_id: int, db: DbSession, current_user: OptionalUser
) -> ProductOut:
    """Fetch one product."""
    product = product_service.get_product(
        db, product_id, include_inactive=bool(current_user and current_user.is_admin)
    )
    if not product.is_active and not (current_user and current_user.is_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found",
        )
    return ProductOut.model_validate(product)


@router.put(
    "/{product_id}",
    response_model=ProductOut,
    summary="Update a product (admin only)",
    description="Partial update of a product. Requires admin privileges (**403** otherwise).",
    responses={
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
        404: {"model": ErrorResponse, "description": "Product not found"},
        422: {"description": "Invalid product data"},
    },
)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: DbSession,
    _admin: CurrentAdmin,
) -> ProductOut:
    """Update a product's fields."""
    product = product_service.get_product(db, product_id)
    return ProductOut.model_validate(product_service.update_product(db, product, payload))


@router.delete(
    "/{product_id}",
    response_model=Message,
    summary="Delete a product (admin only)",
    description=(
        "Soft-deletes a product (`is_active = false`) so existing orders keep "
        "their price history. Returns **403** for non-admins."
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
        404: {"model": ErrorResponse, "description": "Product not found"},
    },
)
def delete_product(product_id: int, db: DbSession, _admin: CurrentAdmin) -> Message:
    """Soft-delete a product."""
    product = product_service.delete_product(db, product_service.get_product(db, product_id))
    return Message(message=f"Product {product.id} deleted")
