"""Admin endpoints and SQL report tests."""

from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------
# Authorisation
# --------------------------------------------------------------------------
def test_statistics_requires_authentication(client: Any) -> None:
    assert client.get("/admin/statistics").status_code == 401


def test_statistics_forbidden_for_normal_user(client: Any, user_auth_headers: dict) -> None:
    assert client.get("/admin/statistics", headers=user_auth_headers).status_code == 403


def test_admin_product_endpoints_forbidden_for_normal_user(
    client: Any, user_auth_headers: dict
) -> None:
    assert (
        client.post(
            "/admin/products", headers=user_auth_headers, json={"name": "X", "price": 1, "stock": 1}
        ).status_code
        == 403
    )
    assert client.put("/admin/products/1", headers=user_auth_headers, json={"stock": 2}).status_code == 403
    assert client.delete("/admin/products/1", headers=user_auth_headers).status_code == 403
    assert client.get("/admin/orders", headers=user_auth_headers).status_code == 403


def test_reports_forbidden_for_normal_user(client: Any, user_auth_headers: dict) -> None:
    assert client.get("/reports/revenue", headers=user_auth_headers).status_code == 403
    assert client.get("/reports/most-purchased-products", headers=user_auth_headers).status_code == 403


# --------------------------------------------------------------------------
# Admin functionality
# --------------------------------------------------------------------------
def test_admin_can_create_update_and_delete_product(
    client: Any, admin_auth_headers: dict
) -> None:
    created = client.post(
        "/admin/products",
        headers=admin_auth_headers,
        json={"name": "Admin Product", "price": 99.0, "stock": 4},
    )
    assert created.status_code == 201
    product_id = created.json()["id"]

    updated = client.put(
        f"/admin/products/{product_id}", headers=admin_auth_headers, json={"stock": 7}
    )
    assert updated.json()["stock"] == 7

    deleted = client.delete(f"/admin/products/{product_id}", headers=admin_auth_headers)
    assert deleted.status_code == 200
    assert deleted.json()["is_active"] is False


def test_admin_can_list_all_orders_and_users(
    client: Any, product: Any, user_auth_headers: dict, admin_auth_headers: dict, mock_stripe: dict
) -> None:
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 1})
    order_id = client.post(
        "/payments/create-checkout-session", headers=user_auth_headers
    ).json()["order_id"]

    orders = client.get("/admin/orders", headers=admin_auth_headers).json()
    assert orders["total"] == 1
    assert orders["items"][0]["id"] == order_id

    users = client.get("/admin/users", headers=admin_auth_headers).json()
    assert users["total"] == 1

    assert client.get(f"/admin/orders/{order_id}", headers=admin_auth_headers).status_code == 200
    assert client.get("/admin/orders/98765", headers=admin_auth_headers).status_code == 404


def test_admin_can_cancel_a_paid_order_and_stock_returns(
    client: Any, db: Any, product: Any, user_auth_headers: dict, admin_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 4})
    order_id = client.post(
        "/payments/create-checkout-session", headers=user_auth_headers
    ).json()["order_id"]

    # Mark it paid through the webhook.
    raw, signature = sign_webhook(
        make_event("checkout.session.completed", {"id": f"cs_test_admin_{order_id}"})
    )
    # Link the session id on the payment first (checkout created its own id).
    from app.models.payment import Payment

    payment = db.query(Payment).filter_by(order_id=order_id).one()
    payment.stripe_session_id = f"cs_test_admin_{order_id}"
    db.commit()
    client.post("/payments/webhook", content=raw, headers={"stripe-signature": signature})

    cancelled = client.put(
        f"/admin/orders/{order_id}/status",
        headers=admin_auth_headers,
        json={"status": "CANCELLED", "cancel_reason": "customer request"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    db.expire_all()
    from app.models.product import Product

    assert db.get(Product, product.id).stock == 10  # 4 units returned to stock


def test_admin_statistics_counts_orders_and_revenue(
    client: Any, db: Any, product: Any, user_auth_headers: dict, admin_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 2})
    order_id = client.post(
        "/payments/create-checkout-session", headers=user_auth_headers
    ).json()["order_id"]

    from app.models.payment import Payment

    payment = db.query(Payment).filter_by(order_id=order_id).one()
    payment.stripe_session_id = "cs_test_stats"
    db.commit()

    raw, signature = sign_webhook(
        make_event("checkout.session.completed", {"id": "cs_test_stats"})
    )
    client.post("/payments/webhook", content=raw, headers={"stripe-signature": signature})

    body = client.get("/admin/statistics", headers=admin_auth_headers).json()
    assert body["total_products"] == 1
    assert body["total_orders"] == 1
    assert body["paid_orders"] == 1
    assert body["pending_orders"] == 0
    assert body["total_revenue"] == 998.0
    assert body["currency"] == "inr"


# --------------------------------------------------------------------------
# SQL reports
# --------------------------------------------------------------------------
def _paid_order(
    client: Any, headers: dict, product: Any, quantity: int, session_suffix: str,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable, db: Any
) -> int:
    client.post("/cart/items", headers=headers, json={"product_id": product.id, "quantity": quantity})
    order_id = client.post("/payments/create-checkout-session", headers=headers).json()["order_id"]

    from app.models.payment import Payment

    session_id = f"cs_test_{session_suffix}"
    payment = db.query(Payment).filter_by(order_id=order_id).one()
    payment.stripe_session_id = session_id
    db.commit()

    raw, signature = sign_webhook(
        make_event("checkout.session.completed", {"id": session_id, "payment_intent": f"pi_{session_suffix}"})
    )
    client.post("/payments/webhook", content=raw, headers={"stripe-signature": signature})
    return order_id


def test_revenue_report_only_counts_paid_orders(
    client: Any, db: Any, product: Any, user_auth_headers: dict, admin_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    _paid_order(client, user_auth_headers, product, 2, "rev1", mock_stripe, sign_webhook, make_event, db)

    body = client.get("/reports/revenue", headers=admin_auth_headers).json()
    assert body["total_revenue"] == 998.0
    assert body["total_paid_orders"] == 1
    assert body["average_order_value"] == 998.0
    assert len(body["daily"]) == 1


def test_most_purchased_products_report(
    client: Any, db: Any, products: list, user_auth_headers: dict, admin_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    _paid_order(client, user_auth_headers, products[0], 5, "mp1", mock_stripe, sign_webhook, make_event, db)
    _paid_order(client, user_auth_headers, products[1], 2, "mp2", mock_stripe, sign_webhook, make_event, db)

    rows = client.get(
        "/reports/most-purchased-products", headers=admin_auth_headers
    ).json()
    assert rows[0]["product_name"] == products[0].name
    assert rows[0]["total_quantity"] == 5
    assert rows[1]["total_quantity"] == 2
    assert rows[0]["revenue"] > rows[1]["revenue"]


def test_orders_per_user_report_includes_users_without_orders(
    client: Any, db: Any, other_user: Any, product: Any, user_auth_headers: dict,
    admin_auth_headers: dict, mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    _paid_order(client, user_auth_headers, product, 1, "ou1", mock_stripe, sign_webhook, make_event, db)

    rows = client.get("/reports/orders-per-user", headers=admin_auth_headers).json()
    by_email = {row["email"]: row for row in rows}

    assert by_email["user@example.com"]["total_orders"] == 1
    assert by_email["user@example.com"]["paid_orders"] == 1
    assert by_email["user@example.com"]["total_spent"] == 499.0
    # The second user never ordered anything but is still listed.
    assert by_email["other@example.com"]["total_orders"] == 0


def test_products_never_purchased_report(
    client: Any, db: Any, products: list, user_auth_headers: dict, admin_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    _paid_order(client, user_auth_headers, products[0], 1, "np1", mock_stripe, sign_webhook, make_event, db)

    rows = client.get("/reports/products-never-purchased", headers=admin_auth_headers).json()
    names = {row["name"] for row in rows}
    assert products[0].name not in names
    assert len(rows) == len(products) - 1


def test_user_order_history_report(
    client: Any, db: Any, product: Any, normal_user: Any, user_auth_headers: dict,
    admin_auth_headers: dict, mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    _paid_order(client, user_auth_headers, product, 1, "h1", mock_stripe, sign_webhook, make_event, db)

    body = client.get(
        f"/reports/user-order-history/{normal_user.id}", headers=admin_auth_headers
    ).json()
    assert body["order_count"] == 1
    assert body["email"] == "user@example.com"
    assert body["orders"][0]["status"] == "PAID"

    assert client.get("/reports/user-order-history/99999", headers=admin_auth_headers).status_code == 404
