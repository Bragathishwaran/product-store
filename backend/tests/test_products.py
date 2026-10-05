"""Product CRUD, pagination and search tests."""

from __future__ import annotations

from typing import Any


def test_admin_can_create_product(client: Any, admin_auth_headers: dict) -> None:
    response = client.post(
        "/products",
        headers=admin_auth_headers,
        json={
            "name": "FastAPI Handbook",
            "description": "Build APIs",
            "price": 599.0,
            "stock": 12,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "FastAPI Handbook"
    assert body["price"] == 599.0
    assert body["stock"] == 12
    assert body["is_active"] is True


def test_non_admin_cannot_create_product(client: Any, user_auth_headers: dict) -> None:
    response = client.post(
        "/products",
        headers=user_auth_headers,
        json={"name": "Sneaky", "price": 10.0, "stock": 1},
    )
    assert response.status_code == 403


def test_unauthenticated_cannot_create_product(client: Any) -> None:
    response = client.post("/products", json={"name": "Anonymous", "price": 10.0, "stock": 1})
    assert response.status_code == 401


def test_create_product_rejects_invalid_data(client: Any, admin_auth_headers: dict) -> None:
    zero_price = client.post(
        "/products", headers=admin_auth_headers, json={"name": "Free", "price": 0, "stock": 5}
    )
    assert zero_price.status_code == 422

    negative_stock = client.post(
        "/products",
        headers=admin_auth_headers,
        json={"name": "Ghost", "price": 10.0, "stock": -3},
    )
    assert negative_stock.status_code == 422

    missing_name = client.post(
        "/products", headers=admin_auth_headers, json={"price": 10.0, "stock": 1}
    )
    assert missing_name.status_code == 422


def test_list_products_pagination(client: Any, products: list) -> None:
    response = client.get("/products", params={"page": 1, "limit": 5})
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {"items", "page", "limit", "total", "total_pages"}
    assert body["page"] == 1
    assert body["limit"] == 5
    assert body["total"] == 15
    assert body["total_pages"] == 3
    assert len(body["items"]) == 5


def test_list_products_second_page(client: Any, products: list) -> None:
    body = client.get("/products", params={"page": 3, "limit": 5}).json()
    assert body["page"] == 3
    assert body["total_pages"] == 3
    assert len(body["items"]) == 5  # 15 items -> third page is full


def test_list_products_last_partial_page(client: Any, products: list) -> None:
    body = client.get("/products", params={"page": 4, "limit": 5}).json()
    assert body["total"] == 15
    assert body["total_pages"] == 3
    assert body["items"] == []


def test_list_products_rejects_invalid_pagination(client: Any, products: list) -> None:
    assert client.get("/products", params={"page": 0, "limit": 5}).status_code == 422
    assert client.get("/products", params={"page": 1, "limit": 0}).status_code == 422
    assert client.get("/products", params={"page": -1, "limit": 5}).status_code == 422


def test_product_search_matches_name(client: Any, products: list) -> None:
    body = client.get("/products", params={"search": "Product 0"}).json()
    assert body["total"] == 9  # Product 01 .. Product 09
    assert all(item["name"].startswith("Product 0") for item in body["items"])


def test_product_search_matches_description(client: Any, products: list) -> None:
    body = client.get("/products", params={"search": "product 7"}).json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Product 07"


def test_product_search_is_case_insensitive_and_paginated(
    client: Any, products: list
) -> None:
    body = client.get("/products", params={"search": "PRODUCT", "limit": 4, "page": 2}).json()
    assert body["total"] == 15
    assert body["total_pages"] == 4
    assert len(body["items"]) == 4


def test_product_search_ignores_sql_wildcards(client: Any, products: list) -> None:
    body = client.get("/products", params={"search": "%"}).json()
    assert body["total"] == 0


def test_get_product_by_id(client: Any, product: Any) -> None:
    response = client.get(f"/products/{product.id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Python Handbook"


def test_get_unknown_product_returns_404(client: Any) -> None:
    assert client.get("/products/999999").status_code == 404


def test_admin_update_product(client: Any, product: Any, admin_auth_headers: dict) -> None:
    response = client.put(
        f"/products/{product.id}",
        headers=admin_auth_headers,
        json={"price": 549.0, "stock": 3},
    )
    assert response.status_code == 200
    assert response.json()["price"] == 549.0
    assert response.json()["stock"] == 3


def test_non_admin_update_product_returns_403(client: Any, product: Any, user_auth_headers: dict) -> None:
    assert (
        client.put(f"/products/{product.id}", headers=user_auth_headers, json={"stock": 99}).status_code
        == 403
    )


def test_delete_product_hides_it_from_public_listing(
    client: Any, product: Any, admin_auth_headers: dict
) -> None:
    assert client.delete(f"/products/{product.id}", headers=admin_auth_headers).status_code == 200

    assert client.get(f"/products/{product.id}").status_code == 404
    assert client.get("/products").json()["total"] == 0
    # Admins can still inspect inactive products.
    assert (
        client.get(f"/products/{product.id}", headers=admin_auth_headers).status_code == 200
    )
