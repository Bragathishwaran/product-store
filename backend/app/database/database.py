"""Database engine, session factory and FastAPI session dependency."""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database.base import Base

# Importing the models package registers every table on `Base.metadata`.
from app import models  # noqa: F401  (side-effect import)

logger = logging.getLogger(__name__)


def _prepare_sqlite_path(url: str) -> None:
    """Create the parent folder for file based SQLite databases."""
    if ":memory:" in url:
        return
    raw_path = url.split("///", 1)[-1]
    if not raw_path or raw_path.startswith(":"):
        return
    Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _engine_kwargs(url: str) -> dict:
    kwargs: dict = {"echo": settings.SQL_ECHO, "future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        # FastAPI / TestClient run endpoints in a thread pool.
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # Keep one shared connection so in-memory data survives.
            kwargs["poolclass"] = StaticPool
    return kwargs


_prepare_sqlite_path(settings.DATABASE_URL)

engine: Engine = create_engine(settings.DATABASE_URL, **_engine_kwargs(settings.DATABASE_URL))


if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        """SQLite ignores foreign keys unless explicitly enabled."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped database session."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create any missing tables (idempotent)."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialised (%s)", settings.DATABASE_URL)


def drop_db() -> None:
    """Drop every table - only used by tests."""
    Base.metadata.drop_all(bind=engine)


def dispose_engine() -> None:
    """Release pooled connections (used on shutdown and in tests)."""
    engine.dispose()
