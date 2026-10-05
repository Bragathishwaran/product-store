"""Authentication routes: register, JSON login and OAuth2 password flow."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.dependencies import DbSession
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, Token
from app.schemas.common import ErrorResponse, Message
from app.schemas.user import UserCreate, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description=(
        "Creates a new account. The password is hashed with bcrypt and the "
        "response never contains the password or its hash. "
        "A duplicate email returns **400 Bad Request**."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Email already registered"},
        422: {"description": "Invalid payload (malformed email, password too short)"},
    },
)
def register(payload: UserCreate, db: DbSession) -> UserOut:
    """Create an account and return the created user (no credentials)."""
    user = auth_service.create_user(
        db, name=payload.name, email=payload.email, password=payload.password
    )
    return UserOut.model_validate(user)


@router.post(
    "/login",
    response_model=Token,
    summary="Login with JSON credentials",
    description="Returns a bearer token. Invalid credentials return **401 Unauthorized**.",
    responses={
        401: {"model": ErrorResponse, "description": "Incorrect email or password"},
        403: {"model": ErrorResponse, "description": "Account is inactive"},
        422: {"description": "Invalid payload"},
    },
)
def login(payload: LoginRequest, db: DbSession) -> Token:
    """Exchange email + password for a JWT access token."""
    user = auth_service.authenticate(db, payload.email, payload.password)
    return Token(access_token=create_access_token(user.id), token_type="bearer")


@router.post(
    "/token",
    response_model=Token,
    summary="Login (OAuth2 password flow)",
    description=(
        "OAuth2-compatible form login (`username` = email, `password`). "
        "Wired to the **Authorize** button in Swagger UI."
    ),
    responses={401: {"model": ErrorResponse, "description": "Incorrect email or password"}},
)
def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> Token:
    """OAuth2 compatible login (form-encoded)."""
    user = auth_service.authenticate(db, form_data.username, form_data.password)
    return Token(access_token=create_access_token(user.id), token_type="bearer")


@router.post(
    "/logout",
    response_model=Message,
    summary="Logout",
    description=(
        "Access tokens are stateless, so the client discards the token. "
        "This endpoint exists so a frontend has a symmetric logout call."
    ),
)
def logout() -> Message:
    return Message(message="Logged out. Discard the access token.")
