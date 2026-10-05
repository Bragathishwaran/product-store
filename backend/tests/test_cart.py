"""Cart tests: add, increment, update, remove, clear and access control."""

from __future__ import annotations

from typing import Any


def test_add_product_to_cart(client: Any, product: Any, user_auth_headers: dict) -> None:
    response = client.post(
        "/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 2}
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["product_id"] == product.id
    assert body["items"][0]["quantity"] == 2
    assert body["items"][0]["unit_price"] == 499.0
    assert body["items"][0]["subtotal"] == 998.0
    assert body["total_items"] == 2
    assert body["total_amount"] == 998.0


def test_adding_same_product_twice_increments_quantity(
    client: Any, product: Any, user_auth_headers: dict
) -> None:
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 2})
    body = client.post(
        "/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 3}
    ).json()

    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 5
    assert body["total_amount"] == 499.0 * 5


def test_add_unknown_product_returns_404(client: Any, user_auth_headers: dict) -> None:
    response = client.post("/cart/items", headers=user_auth_headers, json={"product_id": 4242, "quantity": 1})
    assert response.status_code == 404


def test_add_more_than_available_stock_returns_400(
    client: Any, product: Any, user_auth_headers: dict
) -> None:
    response = client.post(
        "/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 99}
    )
    assert response.status_code == 400
    assert "stock" in response.json()["detail"].lower()


def test_add_inactive_product_returns_400(
    client: Any, db: Any, product: Any, user_auth_headers: dict
) -> None:
    product.is_active = False
    db.commit()

    response = client.post(
        "/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 1}
    )
    assert response.status_code == 400


def test_add_invalid_quantity_returns_422(client: Any, product: Any, user_auth_headers: dict) -> None:
    response = client.post(
        "/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 0}
    )
    assert response.status_code == 422


def test_update_cart_item_quantity(client: Any, product: Any, user_auth_headers: dict) -> None:
    cart = client.post(
        "/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 2}
    ).json()
    item_id = cart["items"][0]["id"]

    response = client.put(
        f"/cart/items/{item_id}", headers=user_auth_headers, json={"quantity": 6}
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["quantity"] == 6
    assert response.json()["total_amount"] == 499.0 * 6


def test_update_unknown_cart_item_returns_404(client: Any, user_auth_headers: dict) -> None:
    response = client.put("/cart/items/9999", headers=user_auth_headers, json={"quantity": 2})
    assert response.status_code == 404


def test_remove_cart_item(client: Any, product: Any, user_auth_headers: dict) -> None:
    cart = client.post(
        "/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 1}
    ).json()
    item_id = cart["items"][0]["id"]

    body = client.delete(f"/cart/items/{item_id}", headers=user_auth_headers).json()
    assert body["items"] == []
    assert body["total_amount"] == 0.0


def test_clear_whole_cart(client: Any, product: Any, products: list, user_auth_headers: dict) -> None:
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 1})
    client.post(
        "/cart/items", headers=user_auth_headers, json={"product_id": products[0].id, "quantity": 2}
    )

    body = client.delete("/cart", headers=user_auth_headers).json()
    assert body["items"] == []
    assert body["total_items"] == 0
    assert body["total_amount"] == 0.0


def test_view_empty_cart_returns_zero_totals(client: Any, user_auth_headers: dict) -> None:
    body = client.get("/cart", headers=user_auth_headers).json()
    assert body["items"] == []
    assert body["total_amount"] == 0.0


def test_cart_requires_authentication(client: Any) -> None:
    assert client.get("/cart").status_code == 401


def test_user_cannot_touch_another_users_cart_item(
    client: Any, product: Any, user_auth_headers: dict, other_auth_headers: dict
) -> None:
    """Each user only ever sees and modifies their own cart."""
    mine = client.post(
        "/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 1}
    ).json()
    assert mine["items"]

    their_cart = client.get("/cart", headers=other_auth_headers).json()
    assert their_cart["items"] == []

    response = client.put(
        f"/cart/items/{mine['items'][0]['id']}", headers=other_auth_headers, json={"quantity": 5}
    )
    assert response.status_code == 404


def test_users_have_separate_carts(
    client: Any, product: Any, user_auth_headers: dict, other_auth_headers: dict
) -> None:
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 3})

    mine = client.get("/cart", headers=user_auth_headers).json()
    theirs = client.get("/cart", headers=other_auth_headers).json()
    assert mine["total_amount"] == 1497.0
    assert theirs["total_amount"] == 0.0
