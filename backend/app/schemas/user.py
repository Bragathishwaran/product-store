"""User schemas.

`UserOut` deliberately has no `password` / `password_hash` field, so a
password can never leak through the API.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel

MIN_PASSWORD_LENGTH = 8
# bcrypt only hashes the first 72 bytes, so that is our hard ceiling.
MAX_PASSWORD_LENGTH = 72


class UserCreate(BaseModel):
    """Registration payload."""

    name: str = Field(min_length=1, max_length=120, examples=["John"])
    email: EmailStr = Field(examples=["john@example.com"])
    password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        examples=["password123"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {"name": "John", "email": "john@example.com", "password": "password123"}
        }
    }


class UserUpdate(BaseModel):
    """Self-service profile update (every field optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=120)


class PasswordChange(BaseModel):
    """Payload for a password change."""

    current_password: str = Field(min_length=1, examples=["password123"])
    new_password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        examples=["newpassword123"],
    )


class UserOut(ORMModel):
    """Safe user representation - never includes credentials."""

    id: int
    name: str
    email: EmailStr
    is_admin: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
