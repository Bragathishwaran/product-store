"""Product schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProductBase(BaseModel):
    """Fields shared by product create payloads."""

    name: str = Field(min_length=1, max_length=200, examples=["Python Handbook"])
    description: str | None = Field(default=None, examples=["A practical guide to Python."])
    price: float = Field(gt=0, le=10_000_000, examples=[499.0])
    stock: int = Field(ge=0, le=1_000_000, examples=[25])


class ProductCreate(ProductBase):
    """Admin payload to create a product."""

    is_active: bool = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Python Handbook",
                "description": "A practical guide to Python.",
                "price": 499.0,
                "stock": 25,
            }
        }
    }


class ProductUpdate(BaseModel):
    """Admin payload to update a product - every field is optional."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    price: float | None = Field(default=None, gt=0, le=10_000_000)
    stock: int | None = Field(default=None, ge=0, le=1_000_000)
    is_active: bool | None = None


class ProductOut(ORMModel):
    """Product representation returned by the API."""

    id: int
    name: str
    description: str | None
    price: float
    stock: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
