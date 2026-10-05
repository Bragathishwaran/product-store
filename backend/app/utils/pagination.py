"""Reusable pagination dependency and the `paginate()` query helper.

`PaginationParams` is injected into routers via :data:`app.core.dependencies.Pagination`,
so invalid `page`/`limit` values are rejected by FastAPI with 422 before any
query runs. `paginate()` then applies `LIMIT`/`OFFSET` and fetches the matching
`COUNT(*)` so the response envelope can report the true number of pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Sequence, TypeVar

from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas.common import DEFAULT_LIMIT, DEFAULT_PAGE, MAX_LIMIT, Page

T = TypeVar("T")

EntityT = TypeVar("EntityT")


@dataclass(frozen=True)
class PaginationParams:
    """Validated ``page`` / ``limit`` pair."""

    page: int = DEFAULT_PAGE
    limit: int = DEFAULT_LIMIT

    @property
    def offset(self) -> int:
        """SQL ``OFFSET`` for the requested page."""
        return (self.page - 1) * self.limit


#: Alias kept for readability inside services (``PageParams``).
PageParams = PaginationParams


def pagination_params(
    page: int = Query(
        DEFAULT_PAGE,
        ge=1,
        description="1-based page number. Must be greater than or equal to 1.",
        examples=[1],
    ),
    limit: int = Query(
        DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=f"Items per page (1-{MAX_LIMIT}).",
        examples=[10],
    ),
) -> PaginationParams:
    """FastAPI dependency for the ``?page=&limit=`` query string."""
    return PaginationParams(page=page, limit=limit)


def paginate(db: Session, statement: Any, params: PaginationParams) -> Page[Any]:
    """Run a paginated query and wrap it in a :class:`Page` envelope.

    The total is a separate ``COUNT(*)`` over the same statement, so the
    database only ever returns the rows for the requested page.
    """
    count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
    total = int(db.execute(count_statement).scalar_one() or 0)

    page_items: Sequence[Any] = db.execute(
        statement.limit(params.limit).offset(params.offset)
    ).scalars().all()

    return Page.build(page_items, page=params.page, limit=params.limit, total=total)