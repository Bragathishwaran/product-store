"""Authentication and user-profile tests."""

from __future__ import annotations

from typing import Any


def test_register_creates_user_and_hides_password(client: Any) -> None:
    response = client.post(
        "/auth/register",
        json={"name": "John", "email": "john@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "john@example.com"
    assert body["name"] == "John"
    assert body["is_admin"] is False
    assert body["is_active"] is True
    # Credentials must never be returned.
    assert "password" not in body
    assert "password_hash" not in body


def test_register_duplicate_email_returns_400(client: Any) -> None:
    payload = {"name": "John", "email": "john@example.com", "password": "password123"}
    assert client.post("/auth/register", json=payload).status_code == 201

    duplicate = client.post("/auth/register", json={**payload, "name": "John 2"})
    assert duplicate.status_code == 400
    assert "already registered" in duplicate.json()["detail"]


def test_register_invalid_email_returns_422(client: Any) -> None:
    response = client.post(
        "/auth/register",
        json={"name": "Bad", "email": "not-an-email", "password": "password123"},
    )
    assert response.status_code == 422
    assert "errors" in response.json()


def test_register_short_password_returns_422(client: Any) -> None:
    response = client.post(
        "/auth/register",
        json={"name": "Short", "email": "short@example.com", "password": "abc"},
    )
    assert response.status_code == 422


def test_login_returns_access_token(client: Any) -> None:
    client.post(
        "/auth/register",
        json={"name": "John", "email": "john@example.com", "password": "password123"},
    )
    response = client.post(
        "/auth/login",
        json={"email": "john@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20


def test_login_with_invalid_password_returns_401(client: Any) -> None:
    client.post(
        "/auth/register",
        json={"name": "John", "email": "john@example.com", "password": "password123"},
    )
    response = client.post(
        "/auth/login", json={"email": "john@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_login_with_unknown_email_returns_401(client: Any) -> None:
    response = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "password123"}
    )
    assert response.status_code == 401


def test_oauth2_token_endpoint_works(client: Any) -> None:
    """The form login used by the Swagger 'Authorize' button."""
    client.post(
        "/auth/register",
        json={"name": "John", "email": "john@example.com", "password": "password123"},
    )
    response = client.post(
        "/auth/token",
        data={"username": "john@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_users_me_requires_authentication(client: Any) -> None:
    assert client.get("/users/me").status_code == 401


def test_users_me_returns_current_user(client: Any, user_auth_headers: dict) -> None:
    response = client.get("/users/me", headers=user_auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"


def test_users_me_rejects_tampered_token(client: Any) -> None:
    response = client.get(
        "/users/me", headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.tampered.sig"}
    )
    assert response.status_code == 401


def test_inactive_user_cannot_access_protected_route(
    client: Any, db: Any, normal_user: Any
) -> None:
    from app.core.security import create_access_token

    normal_user.is_active = False
    db.commit()

    response = client.get(
        "/users/me", headers={"Authorization": f"Bearer {create_access_token(normal_user.id)}"}
    )
    assert response.status_code == 403
