"""FastAPI application entry point.

Run locally with:

    uvicorn app.main:app --reload

Swagger UI: http://127.0.0.1:8000/docs
ReDoc:      http://127.0.0.1:8000/redoc
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.database.database import dispose_engine, engine, init_db
from app.routers import admin, auth, cart, orders, payments, products, reports, users

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")

TAGS_METADATA = [
    {"name": "Authentication", "description": "Register, login and JWT issuing."},
    {"name": "Users", "description": "Authenticated user profile."},
    {"name": "Products", "description": "Catalogue: list, search, paginate (admin-only writes)."},
    {"name": "Cart", "description": "Per-user shopping cart operations."},
    {"name": "Orders", "description": "Order history for the authenticated user."},
    {"name": "Payments", "description": "Stripe Checkout sessions and webhook processing."},
    {"name": "Admin", "description": "Admin-only product, order, user and statistics management."},
    {"name": "Reports", "description": "SQL reports: revenue, best sellers, orders per user."},
    {"name": "Health", "description": "Service and database health."},
]

DESCRIPTION = """
Backend API for the Stackly digital product store.

### Highlights
* JWT authentication (`/auth/register`, `/auth/login`, `/auth/token`) with bcrypt password hashing
* Admin-protected product management with SQL pagination and search
* Per-user cart with server-side totals
* A checkout flow that trusts **only** the database for prices, totals and identity
* Stripe Checkout Session creation plus signature-verified, idempotent webhooks
* Admin statistics and SQL reports (revenue, best sellers, orders per user)

### Authentication
Send `Authorization: Bearer <access_token>` on protected routes, or use the
**Authorize** button in Swagger UI after calling `/auth/login`.

### Status codes
`200` OK - `201` Created - `400` Bad Request - `401` Unauthorized -
`403` Forbidden - `404` Not Found - `422` Unprocessable Entity - `500` Internal Server Error
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup, release connections on shutdown."""
    init_db()
    if settings.uses_insecure_default_secret:
        logger.warning("JWT_SECRET_KEY is still the default value - set a strong secret in .env!")
    if not settings.stripe_enabled:
        logger.warning("STRIPE_SECRET_KEY is not set - checkout requests will fail with 500")
    logger.info(
        "%s v%s ready (database: %s)", settings.PROJECT_NAME, settings.VERSION, settings.DATABASE_URL
    )
    yield
    dispose_engine()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Consistent error responses
# --------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return a compact, predictable 422 body."""
    errors = [
        {"loc": list(error.get("loc", [])), "msg": error.get("msg"), "type": error.get("type")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Validation error", "errors": errors},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak stack traces to API clients."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# --------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(admin.router)
app.include_router(reports.router)


@app.get("/", tags=["Health"], summary="API metadata")
def root() -> dict[str, object]:
    """Basic service information and useful links."""
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
        "health": "/health",
    }


@app.get("/health", tags=["Health"], summary="Health check")
def health() -> dict[str, object]:
    """Report service and database connectivity."""
    database_ok = True
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - only on a broken database
        logger.exception("Database health check failed")
        database_ok = False

    return {
        "status": "ok" if database_ok else "degraded",
        "database": "ok" if database_ok else "unreachable",
        "stripe_configured": settings.stripe_enabled,
    }
