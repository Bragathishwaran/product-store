"""User profile routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentUser, DbSession
from app.schemas.common import ErrorResponse
from app.schemas.user import UserOut, UserUpdate
from app.services import auth_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserOut,
    summary="Get the current user profile",
    description="Returns the authenticated user's profile. Requires a bearer token.",
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid token"},
        403: {"model": ErrorResponse, "description": "Account is inactive"},
    },
)
def read_current_user(current_user: CurrentUser) -> UserOut:
    """Return the profile of the authenticated user."""
    return UserOut.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserOut,
    summary="Update the current user profile",
    description="Lets a user change their own display name.",
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid token"}},
)
def update_current_user(payload: UserUpdate, current_user: CurrentUser, db: DbSession) -> UserOut:
    """Update only the authenticated user's own profile."""
    user = auth_service.update_profile(db, current_user, payload)
    return UserOut.model_validate(user)