# Digital Product Store

A full-stack digital product store built with FastAPI, SQLAlchemy, SQLite by default (PostgreSQL/MySQL supported through SQLAlchemy), React/Vite, Tailwind CSS, and Stripe Checkout. The Stripe webhook—not the browser redirect—is the authority for paid/failed/cancelled order states.

## Project layout

- `backend/app` — FastAPI routes, SQLAlchemy models, schemas, services, JWT and Stripe integration.
- `backend/tests` — pytest API, ownership, pagination, admin/report, and payment/webhook tests.
- `frontend` — React/Vite store and admin pages.

## Requirements

- Python 3.10+
- Node.js 18+ and npm
- Stripe test-mode keys for live Checkout testing; backend/unit tests mock Stripe.

## Backend setup (PowerShell)

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` and set a random `JWT_SECRET_KEY`. SQLite is configured by default and creates `backend/app.db` automatically. To use PostgreSQL, install a compatible driver (for example `psycopg[binary]`) and set `DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ecommerce`. For MySQL, install `pymysql` and configure `mysql+pymysql://user:password@localhost:3306/ecommerce`.

Start the API from the `backend` directory:

```powershell
uvicorn app.main:app --reload
```

Swagger UI: <http://127.0.0.1:8000/docs>  
ReDoc: <http://127.0.0.1:8000/redoc>  
OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

### Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite:///./app.db` |
| `JWT_SECRET_KEY` | Signing key for access tokens; replace before deployment | insecure local placeholder |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime | `60` |
| `STRIPE_SECRET_KEY` | Stripe secret test key (`sk_test_...`) | unset |
| `STRIPE_WEBHOOK_SECRET` | Stripe endpoint signing secret (`whsec_...`) | unset |
| `STRIPE_CURRENCY` | Checkout currency | `inr` |
| `FRONTEND_URL` | Redirect origin for Checkout | `http://localhost:5173` |
| `CORS_ORIGINS` | Comma-separated allowed browser origins | localhost Vite/React origins |
| `DEBUG`, `SQL_ECHO` | Development logging switches | `false` |

### Stripe test-mode setup

1. Use a Stripe **test-mode** secret key in `STRIPE_SECRET_KEY`.
2. Run `stripe listen --forward-to localhost:8000/payments/webhook` using the Stripe CLI and copy its `whsec_...` value to `STRIPE_WEBHOOK_SECRET`.
3. Run both the backend and frontend. Register a user, create products as an admin, add an item to the cart, and choose **Continue to secure checkout**.
4. Complete Checkout with Stripe's test card `4242 4242 4242 4242`, a future expiry, and any CVC/ZIP. The CLI forwards the webhook; the checkout return page polls the authenticated order API and displays PAID only after the webhook updates the database.
5. To test cancellation, use the Checkout back link. To inspect webhook events, use the Stripe CLI output and the order's payment state in `/orders`.

Stripe credentials are intentionally not committed. Actual screenshots require a configured Stripe account/session; the mocked Stripe checkout, signed webhook, signature rejection, idempotency, and stock-update cases in `backend/tests/test_payments.py` provide repeatable local evidence without credentials.

## Frontend setup

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

The frontend defaults to `http://127.0.0.1:8000`. Set `VITE_API_URL` in `frontend/.env.local` to override the API origin. The Vite app runs on <http://127.0.0.1:5173>.

Available pages: `/login`, `/register`, `/products`, `/products/:id`, `/cart`, `/orders`, `/admin/products`, and `/admin/orders`. Admin pages require a user whose `is_admin` flag is true. For a local SQLite development admin, register normally and promote that user directly in the development database:

```powershell
python -c "import sqlite3; db=sqlite3.connect('app.db'); db.execute('UPDATE users SET is_admin = 1 WHERE email = ?', ('admin@example.com',)); db.commit(); db.close()"
```

Replace the email with the registered address. Never expose an unauthenticated admin-creation endpoint.

## API overview

- `POST /auth/register`, `POST /auth/login`, `GET /users/me`
- `GET /products?page=1&limit=10&search=python`; admin writes use `POST/PUT/DELETE /admin/products` (admin-only; equivalent legacy product CRUD paths are also present).
- `GET/POST/PUT/DELETE /cart` and `/cart/items`
- `POST /payments/create-checkout-session`; public, signature-verified `POST /payments/webhook`
- `GET /orders?page=1&limit=5`, `GET /orders/{id}`
- `GET /admin/orders`, `GET /admin/statistics`
- SQL reports: `GET /reports/revenue`, `/reports/most-purchased-products`, `/reports/orders-per-user`, `/reports/products-never-purchased`, and `/reports/user-order-history/{user_id}`.

Pagination responses include `items`, `page`, `limit`, `total`, and `total_pages`. Protected calls use `Authorization: Bearer <access_token>`. Validation errors use 422; unavailable resources and ownership checks return 404/403 respectively.

## Tests and build

From the `backend` directory:

```powershell
python -m pytest
```

From the `frontend` directory:

```powershell
npm run build
```

The backend tests use an isolated SQLite database and mock Stripe Checkout calls; no real Stripe payment or credentials are needed to run them.
