"""Product catalogue service: CRUD, search and database-level pagination."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.schemas.common import Page, build_page
from app.schemas.product import ProductCreate, ProductUpdate
from app.utils.pagination import PaginationParams


def get_product(
    db: Session, product_id: int, *, include_inactive: bool = False
) -> Product:
    """Fetch a product by id, or raise 404.

    Deactivated (soft-deleted) products are reported as missing unless the
    caller explicitly opted in, which is how admins keep full visibility while
    the storefront behaves as if the row never existed.
    """
    product = db.get(Product, product_id)
    if product is None or (not product.is_active and not include_inactive):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found",
        )
    return product


def get_active_product(db: Session, product_id: int) -> Product:
    """Fetch a product that may be ordered right now."""
    return get_product(db, product_id, include_inactive=False)


def list_products(
    db: Session,
    pagination: PaginationParams,
    *,
    search: str | None = None,
    include_inactive: bool = False,
) -> Page[Product]:
    """Return one page of products, optionally filtered by a search term.

    Only ``limit`` rows are loaded; the total comes from a separate
    ``COUNT(*)`` query, so memory use does not grow with the table size.
    """
    filters = []
    if not include_inactive:
        filters.append(Product.is_active.is_(True))

    if search:
        term = search.strip()
        if term:
            # autoescape=True neutralises user supplied % and _ wildcards.
            filters.append(
                Product.name.contains(term, autoescape=True)
                | Product.description.contains(term, autoescape=True)
            )

    count_stmt = select(func.count(Product.id))
    stmt = select(Product)
    if filters:
        count_stmt = count_stmt.where(*filters)
        stmt = stmt.where(*filters)

    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(Product.id)
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
        .scalars()
        .all()
    )
    return build_page(rows, total, pagination.page, pagination.limit)


def create_product(db: Session, payload: ProductCreate) -> Product:
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def update_product(db: Session, product: Product, payload: ProductUpdate) -> Product:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


def delete_product(db: Session, product: Product) -> Product:
    """Soft delete: deactivate so historical order items keep a valid reference."""
    if not product.is_active:
        return product
    product.is_active = False
    db.commit()
    db.refresh(product)
    return product
