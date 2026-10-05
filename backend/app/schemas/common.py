"""Shared schema building blocks: ORM base, messages, errors and pagination."""

from __future__ import annotations

import math
from typing import Generic, Sequence, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

DEFAULT_PAGE = 1
DEFAULT_LIMIT = 10
MAX_LIMIT = 100


class ORMModel(BaseModel):
    """Base for response schemas built straight from SQLAlchemy objects."""

    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    """Simple `{"message": "..."}` success response."""

    message: str


class ErrorResponse(BaseModel):
    """Consistent error body returned by the application exception handlers."""

    detail: str
    errors: list[dict] | None = None


class Page(BaseModel, Generic[T]):
    """Envelope shared by every paginated endpoint.

    `total_pages` is `ceil(total / limit)`, computed in Python from the SQL
    `COUNT(*)`; only `limit` rows are ever loaded from the database.
    """

    items: list[T]
    page: int = Field(ge=1)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)

    @classmethod
    def build(cls, rows: Sequence[T], *, page: int, limit: int, total: int) -> "Page[T]":
        return cls(
            items=list(rows),
            page=page,
            limit=limit,
            total=total,
            total_pages=math.ceil(total / limit) if limit else 0,
        )


def build_page(rows: Sequence[T], total: int, page: int, limit: int) -> Page[T]:
    """Functional alias for :meth:`Page.build` (kept for service readability)."""
    return Page.build(rows, page=page, limit=limit, total=total)
