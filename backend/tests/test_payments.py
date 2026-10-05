"""Payment tests: checkout session creation and Stripe webhook handling."""

from __future__ import annotations

import json
from typing import Any, Callable


def _start_checkout(
    client: Any, headers: dict, product: Any, quantity: int = 2
) -> dict[str, Any]:
    """Put a product in the cart and open a (mocked) checkout session."""
    client.post(
        "/cart/items", headers=headers, json={"product_id": product.id, "quantity": quantity}
    )
    response = client.post("/payments/create-checkout-session", headers=headers)
    assert response.status_code == 201
    return response.json()


# --------------------------------------------------------------------------
# Checkout session creation
# --------------------------------------------------------------------------
def test_checkout_session_is_linked_to_the_order(
    client: Any, product: Any, user_auth_headers: dict, mock_stripe: dict
) -> None:
    body = _start_checkout(client, user_auth_headers, product, quantity=2)

    # Stripe received server-computed values only.
    call = mock_stripe["calls"][0]
    assert call["mode"] == "payment"
    line_item = call["line_items"][0]
    assert line_item["quantity"] == 2
    assert line_item["price_data"]["unit_amount"] == 49900  # 499.00 in paise
    assert call["client_reference_id"] == str(body["order_id"])
    assert call["metadata"]["order_id"] == str(body["order_id"])


def test_checkout_fails_gracefully_on_stripe_error(
    client: Any, product: Any, user_auth_headers: dict, stripe_error: None, db: Any
) -> None:
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 1})

    response = client.post("/payments/create-checkout-session", headers=user_auth_headers)
    assert response.status_code == 500
    assert "unavailable" in response.json()["detail"]

    from app.models.order import Order
    from app.models.enums import OrderStatus

    order = db.query(Order).one()
    assert order.status == OrderStatus.FAILED  # no orphan PENDING order left behind


def test_checkout_without_stripe_configured_returns_500(
    client: Any, product: Any, user_auth_headers: dict, monkeypatch: Any
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    client.post("/cart/items", headers=user_auth_headers, json={"product_id": product.id, "quantity": 1})

    response = client.post("/payments/create-checkout-session", headers=user_auth_headers)
    assert response.status_code == 500


# --------------------------------------------------------------------------
# Webhook security
# --------------------------------------------------------------------------
def test_webhook_without_signature_returns_400(client: Any) -> None:
    response = client.post("/payments/webhook", content=b"{}")
    assert response.status_code == 400


def test_webhook_with_invalid_signature_returns_400(client: Any, sign_webhook: Callable) -> None:
    raw, _ = sign_webhook({"id": "evt_1", "type": "checkout.session.completed"})
    response = client.post(
        "/payments/webhook", content=raw, headers={"stripe-signature": "t=1,v1=deadbeef"}
    )
    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()


def test_webhook_with_signature_from_wrong_secret_returns_400(
    client: Any, sign_webhook: Callable
) -> None:
    raw, signature = sign_webhook(
        {"id": "evt_1", "type": "checkout.session.completed"}, secret="whsec_attacker_secret"
    )
    response = client.post(
        "/payments/webhook", content=raw, headers={"stripe-signature": signature}
    )
    assert response.status_code == 400


def test_webhook_with_malformed_payload_returns_400(client: Any, sign_webhook: Callable) -> None:
    _, signature = sign_webhook({"id": "evt_1"})
    response = client.post(
        "/payments/webhook", content=b"not-json", headers={"stripe-signature": signature}
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Webhook processing
# --------------------------------------------------------------------------
def test_unpaid_checkout_completion_waits_for_async_payment_success(
    client: Any,
    db: Any,
    product: Any,
    user_auth_headers: dict,
    mock_stripe: dict,
    sign_webhook: Callable,
    make_event: Callable,
) -> None:
    checkout = _start_checkout(client, user_auth_headers, product, quantity=2)

    unpaid_event = make_event(
        "checkout.session.completed",
        {
            "id": checkout["session_id"],
            "payment_status": "unpaid",
            "metadata": {"order_id": str(checkout["order_id"])},
        },
    )
    raw, signature = sign_webhook(unpaid_event)
    response = client.post(
        "/payments/webhook", content=raw, headers={"stripe-signature": signature}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    order = client.get(
        f"/orders/{checkout['order_id']}", headers=user_auth_headers
    ).json()
    assert order["status"] == "PENDING"
    assert order["payment"]["status"] == "PENDING"

    success_event = make_event(
        "checkout.session.async_payment_succeeded",
        {
            "id": checkout["session_id"],
            "payment_status": "paid",
            "metadata": {"order_id": str(checkout["order_id"])},
        },
    )
    raw, signature = sign_webhook(success_event)
    response = client.post(
        "/payments/webhook", content=raw, headers={"stripe-signature": signature}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    order = client.get(
        f"/orders/{checkout['order_id']}", headers=user_auth_headers
    ).json()
    assert order["status"] == "PAID"
    db.expire_all()
    from app.models.product import Product

    assert db.get(Product, product.id).stock == 8


def test_checkout_completed_marks_order_paid_and_deducts_stock(
    client: Any, db: Any, product: Any, user_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    checkout = _start_checkout(client, user_auth_headers, product, quantity=2)
    event = make_event(
        "checkout.session.completed",
        {
            "id": checkout["session_id"],
            "object": "checkout.session",
            "payment_intent": "pi_test_123",
            "metadata": {"order_id": str(checkout["order_id"])},
        },
    )
    raw, signature = sign_webhook(event)

    response = client.post(
        "/payments/webhook", content=raw, headers={"stripe-signature": signature}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["received"] is True
    assert body["status"] == "processed"
    assert body["order_id"] == checkout["order_id"]

    order = client.get(f"/orders/{checkout['order_id']}", headers=user_auth_headers).json()
    assert order["status"] == "PAID"
    assert order["payment"]["status"] == "PAID"
    assert order["payment"]["stripe_payment_intent_id"] == "pi_test_123"

    db.expire_all()
    from app.models.product import Product

    assert db.get(Product, product.id).stock == 8  # 10 - 2


def test_duplicate_webhook_delivery_is_idempotent(
    client: Any, db: Any, product: Any, user_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    checkout = _start_checkout(client, user_auth_headers, product, quantity=3)
    event = make_event(
        "checkout.session.completed",
        {"id": checkout["session_id"], "payment_intent": "pi_test_dup"},
        event_id="evt_replayed_1",
    )
    raw, signature = sign_webhook(event)
    headers = {"stripe-signature": signature}

    first = client.post("/payments/webhook", content=raw, headers=headers)
    second = client.post("/payments/webhook", content=raw, headers=headers)

    assert first.json()["status"] == "processed"
    assert second.json()["status"] == "duplicate"

    db.expire_all()
    from app.models.order import Order
    from app.models.order_item import OrderItem
    from app.models.payment import Payment
    from app.models.product import Product

    # No duplicate orders/items/payments and stock deducted exactly once.
    assert db.query(Order).count() == 1
    assert db.query(OrderItem).count() == 1
    assert db.query(Payment).count() == 1
    assert db.get(Product, product.id).stock == 7  # 10 - 3


def test_new_event_for_already_paid_order_does_not_deduct_stock_twice(
    client: Any, db: Any, product: Any, user_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    checkout = _start_checkout(client, user_auth_headers, product, quantity=2)

    for event_id, event_type in (
        ("evt_a", "checkout.session.completed"),
        ("evt_b", "payment_intent.succeeded"),
    ):
        payload = {
            "id": checkout["session_id"] if event_type.startswith("checkout") else "pi_test_999",
            "object": "checkout.session" if event_type.startswith("checkout") else "payment_intent",
            "payment_intent": "pi_test_999",
            "metadata": {"order_id": str(checkout["order_id"])},
        }
        raw, signature = sign_webhook(
            make_event(event_type, payload, event_id=event_id)
        )
        client.post("/payments/webhook", content=raw, headers={"stripe-signature": signature})

    db.expire_all()
    from app.models.product import Product

    assert db.get(Product, product.id).stock == 8


def test_expired_checkout_session_cancels_order(
    client: Any, db: Any, product: Any, user_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    checkout = _start_checkout(client, user_auth_headers, product, quantity=1)
    event = make_event(
        "checkout.session.expired",
        {"id": checkout["session_id"], "metadata": {"order_id": str(checkout["order_id"])}},
    )
    raw, signature = sign_webhook(event)

    response = client.post(
        "/payments/webhook", content=raw, headers={"stripe-signature": signature}
    )
    assert response.status_code == 200

    order = client.get(f"/orders/{checkout['order_id']}", headers=user_auth_headers).json()
    assert order["status"] == "CANCELLED"
    assert order["payment"]["status"] == "CANCELLED"

    db.expire_all()
    from app.models.product import Product

    assert db.get(Product, product.id).stock == 10  # stock untouched


def test_failed_payment_marks_order_failed(
    client: Any, db: Any, product: Any, user_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    checkout = _start_checkout(client, user_auth_headers, product, quantity=1)
    event = make_event(
        "payment_intent.payment_failed",
        {
            "id": "pi_test_fail",
            "object": "payment_intent",
            "metadata": {"order_id": str(checkout["order_id"])},
        },
    )
    raw, signature = sign_webhook(event)

    client.post("/payments/webhook", content=raw, headers={"stripe-signature": signature})

    order = client.get(f"/orders/{checkout['order_id']}", headers=user_auth_headers).json()
    assert order["status"] == "FAILED"
    assert order["payment"]["status"] == "FAILED"

    db.expire_all()
    from app.models.product import Product

    assert db.get(Product, product.id).stock == 10


def test_unknown_event_type_is_acknowledged_and_ignored(
    client: Any, sign_webhook: Callable, make_event: Callable
) -> None:
    event = make_event("customer.created", {"id": "cus_123"})
    raw, signature = sign_webhook(event)

    response = client.post(
        "/payments/webhook", content=raw, headers={"stripe-signature": signature}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webhook_for_unknown_order_is_ignored(
    client: Any, sign_webhook: Callable, make_event: Callable
) -> None:
    event = make_event(
        "checkout.session.completed",
        {"id": "cs_test_unknown", "metadata": {"order_id": "424242"}},
    )
    raw, signature = sign_webhook(event)

    response = client.post(
        "/payments/webhook", content=raw, headers={"stripe-signature": signature}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_successful_payment_empties_purchased_cart_lines(
    client: Any, product: Any, user_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    checkout = _start_checkout(client, user_auth_headers, product, quantity=2)
    event = make_event(
        "checkout.session.completed",
        {"id": checkout["session_id"], "payment_intent": "pi_test_cart"},
    )
    raw, signature = sign_webhook(event)
    client.post("/payments/webhook", content=raw, headers={"stripe-signature": signature})

    cart = client.get("/cart", headers=user_auth_headers).json()
    assert cart["items"] == []
    assert cart["total_amount"] == 0.0


def test_payment_status_endpoint_reflects_webhook(
    client: Any, product: Any, user_auth_headers: dict,
    mock_stripe: dict, sign_webhook: Callable, make_event: Callable
) -> None:
    checkout = _start_checkout(client, user_auth_headers, product, quantity=1)
    assert (
        client.get(f"/payments/order/{checkout['order_id']}", headers=user_auth_headers).json()["status"]
        == "PENDING"
    )

    raw, signature = sign_webhook(
        make_event("checkout.session.completed", {"id": checkout["session_id"]})
    )
    client.post("/payments/webhook", content=raw, headers={"stripe-signature": signature})

    body = client.get(f"/payments/order/{checkout['order_id']}", headers=user_auth_headers).json()
    assert body["status"] == "PAID"
