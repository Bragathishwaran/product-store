"""SQLAlchemy declarative base and the shared timestamp mixin."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware "now", used as the Python-side column default."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class every ORM model inherits from (owns ``Base.metadata``)."""


class TimestampMixin:
    """Adds self-populating ``created_at`` / ``updated_at`` columns."""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
