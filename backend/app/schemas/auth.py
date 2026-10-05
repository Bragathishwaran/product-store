"""Authentication schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.user import UserCreate


class LoginRequest(BaseModel):
    """JSON login payload."""

    email: str = Field(examples=["john@example.com"])
    password: str = Field(min_length=1, examples=["password123"])

    model_config = {
        "json_schema_extra": {
            "example": {"email": "john@example.com", "password": "password123"}
        }
    }


class Token(BaseModel):
    """OAuth2-style bearer token response."""

    access_token: str
    token_type: str = Field(default="bearer", examples=["bearer"])


__all__ = ["LoginRequest", "Token", "UserCreate"]
