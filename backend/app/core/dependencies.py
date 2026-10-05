"""Reusable FastAPI dependencies: JWT validation, roles and pagination.

Protected routes depend on `get_current_user` / `get_current_admin`, so JWT
verification exists exactly once in the whole project instead of being
duplicated in every router.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database.database import get_db
from app.models.user import User
from app.schemas.common import DEFAULT_LIMIT, MAX_LIMIT
from app.utils.pagination import PaginationParams

# Makes the "Authorize" button work in Swagger UI (/docs).
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="auth/token",
    auto_error=False,
    description="JWT access token. Log in via /auth/login, then paste the token here.",
)


def credentials_exception(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_from_token(token: str | None, db: Session) -> User | None:
    """Decode a bearer token and return its user, or None if it is not usable."""
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except JWTError:
        return None
    subject = payload.get("sub")
    if subject is None:
        return None
    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        return None
    return db.get(User, user_id)


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the authenticated user from the bearer token (401 when invalid)."""
    if not token:
        raise credentials_exception("Not authenticated")

    user = _user_from_token(token, db)
    if user is None:
        # Covers a bad/expired signature *and* a token for a deleted user.
        raise credentials_exception("Invalid or expired token")
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    return user


def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)]
) -> User:
    """`get_current_user` already rejects inactive accounts."""
    return current_user


def get_current_admin(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Only administrators may proceed (403 for regular users)."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


def get_optional_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    """Like `get_current_user` but returns None instead of raising.

    Used by public endpoints that widen their response for admins (being able
    to see inactive products).
    """
    user = _user_from_token(token, db)
    return user if user is not None and user.is_active else None


def get_pagination(
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Items per page")] = DEFAULT_LIMIT,
) -> PaginationParams:
    """Validate and normalise the ``?page=&limit=`` query parameters."""
    return PaginationParams(page=page, limit=limit)


# --- Annotated aliases used directly in router signatures -------------------
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_active_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
Pagination = Annotated[PaginationParams, Depends(get_pagination)]
