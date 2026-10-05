"""Order tests: checkout creation, ownership rules and pagination."""

from __future__ import annotations

from typing import Any


def test_checkout_with_empty_cart_returns_400(client: Any, user_auth_headers: dict) -> None:
    response = client.post("/payments/create-checkout-session", headers=user_auth_headers)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_checkout_creates_pending_order_with_server_totals(
    client: Any, product: Any, user_auth_headers: dict, mock_stripe: dict
) -> None:
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 2})

    response = client.post("/payments/create-checkout-session", headers=user_auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["session_id"].startswith("cs_test_")
    assert body["checkout_url"].startswith("https://checkout.stripe.com/")
    assert body["amount"] == 998.0
    assert body["status"] == "PENDING"

    order = client.get(f"/orders/{body['order_id']}", headers=user_auth_headers).json()
    assert order["status"] == "PENDING"
    assert order["total_amount"] == 998.0
    assert order["items"][0]["unit_price"] == 499.0
    assert order["payment"]["status"] == "PENDING"
    assert order["payment"]["stripe_session_id"] == body["session_id"]


def test_checkout_requires_authentication(client: Any) -> None:
    assert client.post("/payments/create-checkout-session").status_code == 401


def test_order_listing_is_paginated(
    client: Any, db: Any, product: Any, user_auth_headers: dict, mock_stripe: dict
) -> None:
    for _ in range(3):
        client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 1})
        client.post("/payments/create-checkout-session", headers=user_auth_headers)

    body = client.get("/orders", params={"page": 1, "limit": 2}, headers=user_auth_headers).json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["limit"] == 2
    assert body["total_pages"] == 2
    assert len(body["items"]) == 2

    body = client.get("/orders", params={"page": 2, "limit": 2}, headers=user_auth_headers).json()
    assert len(body["items"]) == 1


def test_order_listing_rejects_invalid_pagination(client: Any, user_auth_headers: dict) -> None:
    assert (
        client.get("/orders", params={"page": 0, "limit": 5}, headers=user_auth_headers).status_code
        == 422
    )


def test_order_listing_only_returns_own_orders(
    client: Any, product: Any, user_auth_headers: dict, other_auth_headers: dict, mock_stripe: dict
) -> None:
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 1})
    client.post("/payments/create-checkout-session", headers=user_auth_headers)

    assert client.get("/orders", headers=other_auth_headers).json()["total"] == 0


def test_user_cannot_read_another_users_order(
    client: Any, product: Any, user_auth_headers: dict, other_auth_headers: dict, mock_stripe: dict
) -> None:
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 1})
    order_id = client.post(
        "/payments/create-checkout-session", headers=user_auth_headers
    ).json()["order_id"]

    assert client.get(f"/orders/{order_id}", headers=user_auth_headers).status_code == 200
    assert client.get(f"/orders/{order_id}", headers=other_auth_headers).status_code == 403


def test_unknown_order_returns_404(client: Any, user_auth_headers: dict) -> None:
    assert client.get("/orders/987654", headers=user_auth_headers).status_code == 404


def test_orders_require_authentication(client: Any) -> None:
    assert client.get("/orders").status_code == 401
