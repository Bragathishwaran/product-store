"""Pytest fixtures.

The whole test suite runs against a **separate SQLite database**
(`sqlite:///./test.db`, overridable with `TEST_DATABASE_URL`) through a
`get_db` dependency override - the development/production database is never
touched. Stripe is mocked, so no network access and no real keys are needed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Callable
from uuid import uuid4

import pytest

# --- Test environment -------------------------------------------------------
# These must be set BEFORE the application (and therefore settings) is imported.
os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "sqlite:///./test.db"))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-used-in-production")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake_key_for_tests")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_secret_for_tests")
os.environ.setdefault("STRIPE_CURRENCY", "inr")

import stripe  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.product import ProductCreate  # noqa: E402
from app.services import auth_service, cart_service, product_service  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
TEST_DB_FILE = TEST_DATABASE_URL.split("///")[-1]

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
TestingSessionLocal = sessionmaker(
    bind=test_engine, autocommit=False, autoflush=False, expire_on_commit=False
)


# --------------------------------------------------------------------------
# Database / client
# --------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def create_schema() -> Any:
    """Create the test schema once for the whole session."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield test_engine
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    if os.path.isfile(TEST_DB_FILE):  # pragma: no cover - cleanup convenience
        os.remove(TEST_DB_FILE)


@pytest.fixture()
def db() -> Any:
    """A database session bound to the test database."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_tables(db: Any) -> Any:
    """Guarantee every test starts from an empty database."""
    yield
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()


@pytest.fixture()
def client() -> Any:
    """FastAPI test client with `get_db` overridden to the test database."""
    def override_get_db() -> Any:
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# Users / auth
# --------------------------------------------------------------------------
def bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def normal_user(db: Any) -> User:
    return auth_service.create_user(
        db, name="Regular User", email="user@example.com", password="password123"
    )


@pytest.fixture()
def other_user(db: Any) -> User:
    return auth_service.create_user(
        db, name="Other User", email="other@example.com", password="password123"
    )


@pytest.fixture()
def admin_user(db: Any) -> User:
    return auth_service.create_user(
        db,
        name="Admin User",
        email="admin@example.com",
        password="password123",
        is_admin=True,
    )


@pytest.fixture()
def user_auth_headers(normal_user: User) -> dict[str, str]:
    return bearer(normal_user)


@pytest.fixture()
def other_auth_headers(other_user: User) -> dict[str, str]:
    return bearer(other_user)


@pytest.fixture()
def admin_auth_headers(admin_user: User) -> dict[str, str]:
    return bearer(admin_user)


# --------------------------------------------------------------------------
# Products / cart
# --------------------------------------------------------------------------
@pytest.fixture()
def product(db: Any) -> Any:
    return product_service.create_product(
        db,
        ProductCreate(
            name="Python Handbook",
            description="A practical guide to Python",
            price=499.0,
            stock=10,
        ),
    )


@pytest.fixture()
def products(db: Any) -> list[Any]:
    """15 products so pagination can be asserted (pages of 5)."""
    return [
        product_service.create_product(
            db,
            ProductCreate(
                name=f"Product {index:02d}",
                description=f"Description for product {index}",
                price=100.0 + index,
                stock=50,
            ),
        )
        for index in range(1, 16)
    ]


@pytest.fixture()
def cart(db: Any, normal_user: User) -> Any:
    return cart_service.get_or_create_cart(db, normal_user.id)


# --------------------------------------------------------------------------
# Stripe test doubles
# --------------------------------------------------------------------------
@pytest.fixture()
def mock_stripe(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace `stripe.checkout.Session.create` with a fake (no HTTP calls)."""
    state: dict[str, Any] = {"sessions": {}, "calls": []}

    def fake_create(**kwargs: Any) -> Any:
        session_id = f"cs_test_{uuid4().hex[:16]}"
        payload = {
            "id": session_id,
            "object": "checkout.session",
            "url": f"https://checkout.stripe.com/c/pay/{session_id}#fidtest",
            "status": "open",
            "payment_status": "unpaid",
            "client_reference_id": kwargs.get("client_reference_id"),
            "metadata": kwargs.get("metadata", {}),
        }
        state["sessions"][session_id] = payload
        state["calls"].append(kwargs)
        return stripe.checkout.Session.construct_from(payload, "sk_test_fake")

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(fake_create))
    return state


@pytest.fixture()
def stripe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make Stripe raise an API error."""
    def boom(**_: Any) -> Any:
        raise stripe.StripeError("Simulated Stripe API failure")

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(boom))


@pytest.fixture()
def sign_webhook() -> Callable[..., tuple[bytes, str]]:
    """Return a callable producing a `(raw_body, stripe-signature)` pair.

    Implements Stripe's documented scheme:
    `v1 = HMAC_SHA256(t + "." + payload, webhook_secret)`.
    """

    def _sign(
        payload: dict[str, Any],
        *,
        secret: str | None = None,
        timestamp: int | None = None,
    ) -> tuple[bytes, str]:
        webhook_secret = secret or os.environ["STRIPE_WEBHOOK_SECRET"]
        raw = json.dumps(payload).encode("utf-8")
        ts = timestamp if timestamp is not None else int(time.time())
        signature = hmac.new(
            webhook_secret.encode("utf-8"),
            f"{ts}.".encode("utf-8") + raw,
            hashlib.sha256,
        ).hexdigest()
        return raw, f"t={ts},v1={signature}"

    return _sign


@pytest.fixture()
def make_event() -> Callable[..., dict[str, Any]]:
    """Build a Stripe event payload."""
    counter = {"value": 0}

    def _make(
        event_type: str,
        obj: dict[str, Any],
        *,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        counter["value"] += 1
        if event_type == "checkout.session.completed" and "payment_status" not in obj:
            obj = {**obj, "payment_status": "paid"}
        return {
            "id": event_id or f"evt_test_{uuid4().hex[:12]}_{counter['value']}",
            "object": "event",
            "api_version": "2024-06-20",
            "type": event_type,
            "data": {"object": obj},
        }

    return _make
