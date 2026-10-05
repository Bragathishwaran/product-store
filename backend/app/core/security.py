"""Password hashing and JWT encoding/decoding primitives.

Passwords are hashed with `bcrypt` directly (see requirements.txt for why
`passlib` is not used). Tokens are signed JWTs (`python-jose`) containing the
user id as the `sub` claim plus `iat`/`exp`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# bcrypt only considers the first 72 bytes of a password.
MAX_PASSWORD_BYTES = 72
BCRYPT_ROUNDS = 12


def _encode_password(password: str) -> bytes:
    """Encode and defensively truncate to bcrypt's 72-byte limit."""
    return password.encode("utf-8")[:MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    """Return a bcrypt hash (never the plain-text password)."""
    return bcrypt.hashpw(_encode_password(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    if not plain_password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(_encode_password(plain_password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash stored in the database - treat as a failed login.
        return False


def create_access_token(
    subject: str | int,
    *,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token for the given subject (user id)."""
    minutes = expires_minutes if expires_minutes is not None else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    issued_at = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(issued_at.timestamp()),
        "exp": issued_at + timedelta(minutes=minutes),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT.

    Raises:
        JWTError: if the token is malformed, tampered with, wrong algorithm or expired.
    """
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
