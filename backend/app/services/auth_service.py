"""Authentication and user service."""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.common import Page, build_page
from app.schemas.user import UserCreate, UserUpdate
from app.utils.pagination import PaginationParams

logger = logging.getLogger(__name__)


def normalize_email(email: str) -> str:
    """Emails are compared case-insensitively and stored lowercased."""
    return email.strip().lower()


def get_by_email(db: Session, email: str) -> User | None:
    return db.execute(
        select(User).where(func.lower(User.email) == normalize_email(email))
    ).scalar_one_or_none()


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


#: Alias used by the reports router.
get_user_by_id = get_by_id


def create_user(
    db: Session,
    *,
    name: str,
    email: str,
    password: str,
    is_admin: bool = False,
) -> User:
    """Create a user. Raises 400 when the email is already registered."""
    email = normalize_email(email)
    if get_by_email(db, email) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    user = User(
        name=name.strip(),
        email=email,
        # Only ever store the hash - never the plain-text password.
        password_hash=hash_password(password),
        is_admin=is_admin,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent registration with the same email.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )
    db.refresh(user)
    logger.info("Registered user id=%s", user.id)
    return user


def register_user(db: Session, payload: UserCreate) -> User:
    """Registration entry point used by the router."""
    return create_user(
        db, name=payload.name, email=payload.email, password=payload.password
    )


def authenticate(db: Session, email: str, password: str) -> User:
    """Validate credentials, returning the user or raising 401/403."""
    user = get_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        # Deliberately vague: never reveal whether the email exists.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    return user


def issue_token(user: User) -> dict[str, str]:
    """Mint a signed bearer token for ``user``."""
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
    }


def update_user_profile(db: Session, user: User, payload: UserUpdate) -> User:
    """Apply a partial profile update to the authenticated user."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(user)
    return user


def change_password(
    db: Session, user: User, current_password: str, new_password: str
) -> None:
    """Rotate the password after re-verifying the current one."""
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    user.password_hash = hash_password(new_password)
    db.commit()


def list_users(
    db: Session, pagination: PaginationParams, search: str | None = None
) -> Page[User]:
    """Paginated user listing with optional name/email search (admin only)."""
    stmt = select(User).where(User.is_admin.is_(False))
    count_stmt = select(func.count(User.id)).where(User.is_admin.is_(False))
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        condition = or_(User.name.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\"))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt
            .order_by(User.id)
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
        .scalars()
        .all()
    )
    return build_page(rows, total, pagination.page, pagination.limit)
