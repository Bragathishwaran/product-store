"""Generic pagination response schema."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageRead(BaseModel, Generic[T]):
    """Paginated collection envelope."""

    items: list[T]
    page: int = Field(ge=1, examples=[1])
    limit: int = Field(ge=1, examples=[10])
    total: int = Field(ge=0, examples=[25])
    total_pages: int = Field(ge=0, examples=[3])
