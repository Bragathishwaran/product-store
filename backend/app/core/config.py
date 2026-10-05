"""Application settings loaded from environment variables / `.env` file.

Secrets are never hardcoded in source: the JWT secret and the Stripe keys are
read from the environment (or from a local `.env`). Copy `.env.example` to
`.env` and fill in your own values.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/ - the project root that contains app/, tests/ and requirements.txt
BASE_DIR = Path(__file__).resolve().parent.parent.parent

#: Placeholder that must be replaced before running anywhere but locally.
INSECURE_DEFAULT_SECRET = "change_this_secret"

#: Stripe substitutes this placeholder in Checkout redirect URLs.
CHECKOUT_SESSION_ID = "{CHECKOUT_SESSION_ID}"


class Settings(BaseSettings):
    """Typed configuration container backed by environment variables."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    PROJECT_NAME: str = "E-Commerce API"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = (
        "Production-style backend for an e-commerce platform: JWT authentication, "
        "product catalogue with pagination and search, cart, orders, Stripe Checkout "
        "with webhook-driven payment status, admin tooling and SQL reports."
    )
    DEBUG: bool = False

    # --- Database ----------------------------------------------------------
    # SQLite by default. Any SQLAlchemy URL works, e.g.
    #   postgresql+psycopg://user:pass@localhost:5432/ecommerce
    #   mysql+pymysql://user:pass@localhost:3306/ecommerce
    DATABASE_URL: str = "sqlite:///./app.db"
    SQL_ECHO: bool = False

    # --- JWT ---------------------------------------------------------------
    JWT_SECRET_KEY: str = INSECURE_DEFAULT_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # --- Stripe (test mode) -------------------------------------------------
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_CURRENCY: str = "inr"
    FRONTEND_URL: str = "http://localhost:5173"
    STRIPE_SUCCESS_URL: str | None = None
    STRIPE_CANCEL_URL: str | None = None

    # --- CORS (a React dev server can be pointed at this API later) ---------
    CORS_ORIGINS: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    @field_validator("STRIPE_CURRENCY", mode="before")
    @classmethod
    def _normalise_currency(cls, value: object) -> object:
        return str(value).strip().lower() if value else "inr"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Allow a comma separated list in the env file."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # --- Derived helpers ----------------------------------------------------
    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def uses_insecure_default_secret(self) -> bool:
        return self.JWT_SECRET_KEY == INSECURE_DEFAULT_SECRET

    @property
    def cors_origin_list(self) -> List[str]:
        return list(self.CORS_ORIGINS)

    @property
    def stripe_is_configured(self) -> bool:
        """Stripe calls are only possible with a secret key."""
        return bool(self.STRIPE_SECRET_KEY)

    @property
    def stripe_enabled(self) -> bool:
        """Alias of :attr:`stripe_is_configured` (kept for call-site readability)."""
        return self.stripe_is_configured

    @property
    def stripe_webhooks_configured(self) -> bool:
        """Webhook signatures can only be verified with a signing secret."""
        return bool(self.STRIPE_WEBHOOK_SECRET)

    @property
    def success_url(self) -> str:
        """Where Stripe redirects the buyer after a successful payment."""
        if self.STRIPE_SUCCESS_URL:
            return self.STRIPE_SUCCESS_URL
        return (
            f"{self.FRONTEND_URL.rstrip('/')}/checkout/success"
            f"?session_id={CHECKOUT_SESSION_ID}"
        )

    @property
    def cancel_url(self) -> str:
        """Where Stripe redirects the buyer when checkout is abandoned."""
        if self.STRIPE_CANCEL_URL:
            return self.STRIPE_CANCEL_URL
        return f"{self.FRONTEND_URL.rstrip('/')}/checkout/cancel"

    def assert_production_ready(self) -> None:
        """Warn loudly about configuration that is fine locally but not in prod."""
        import logging

        logger = logging.getLogger(__name__)
        if self.uses_insecure_default_secret:
            logger.warning(
                "JWT_SECRET_KEY still uses the example value. "
                "Set a strong, unique secret before deploying."
            )
        if not self.stripe_is_configured:
            logger.warning("STRIPE_SECRET_KEY is not set - checkout endpoints will return 503.")


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (single source of truth for the process)."""
    return Settings()


settings = get_settings()
