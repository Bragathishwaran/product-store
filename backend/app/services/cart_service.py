"""Cart business logic. Every operation is scoped to the authenticated user."""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cart import Cart
from app.models.cart_item import CartItem
from app.models.product import Product
from app.models.user import User
from app.schemas.cart import CartItemOut, CartOut
from app.utils.money import to_decimal


def get_or_create_cart(db: Session, user_id: int) -> Cart:
    """Return the cart for ``user_id``, creating an empty one on first use."""
    cart = db.execute(select(Cart).where(Cart.user_id == user_id)).scalar_one_or_none()
    if cart is None:
        cart = Cart(user_id=user_id)
        db.add(cart)
        db.commit()
        db.refresh(cart)
    return cart


def get_cart(db: Session, user: User) -> Cart:
    """Return the authenticated user's cart."""
    return get_or_create_cart(db, user.id)


def _get_sellable_product(db: Session, product_id: int) -> Product:
    """Fetch a product that is allowed to be ordered."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found.",
        )
    if not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product '{product.name}' is no longer available.",
        )
    return product


def _get_owned_item(db: Session, cart: Cart, item_id: int) -> CartItem:
    """Fetch a cart line, refusing to reveal items owned by somebody else."""
    item = db.get(CartItem, item_id)
    if item is None or item.cart_id != cart.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cart item {item_id} not found.",
        )
    return item


def _require_stock(product: Product, quantity: int) -> None:
    if product.stock < quantity:
        detail = (
            f"Only {product.stock} unit(s) of '{product.name}' left in stock."
            if product.stock
            else f"'{product.name}' is out of stock."
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=detail
        )


def add_item(db: Session, user: User, product_id: int, quantity: int) -> Cart:
    """Add a product, or increment its quantity if it is already in the cart."""
    cart = get_cart(db, user)
    product = _get_sellable_product(db, product_id)

    existing = db.execute(
        select(CartItem).where(
            CartItem.cart_id == cart.id, CartItem.product_id == product_id
        )
    ).scalar_one_or_none()

    # Stock is validated against the resulting quantity, not the delta.
    _require_stock(product, quantity + (existing.quantity if existing else 0))

    if existing is not None:
        existing.quantity += quantity
    else:
        db.add(CartItem(cart_id=cart.id, product_id=product.id, quantity=quantity))

    db.commit()
    db.refresh(cart)
    return cart


def update_item(db: Session, user: User, item_id: int, quantity: int) -> Cart:
    """Set an absolute quantity on an existing cart line."""
    cart = get_cart(db, user)
    item = _get_owned_item(db, cart, item_id)
    product = _get_sellable_product(db, item.product_id)
    _require_stock(product, quantity)

    item.quantity = quantity
    db.commit()
    db.refresh(cart)
    return cart


def remove_item(db: Session, user: User, item_id: int) -> Cart:
    """Delete one cart line."""
    cart = get_cart(db, user)
    item = _get_owned_item(db, cart, item_id)
    db.delete(item)
    db.commit()
    db.refresh(cart)
    return cart


def clear_cart(db: Session, user: User) -> Cart:
    """Remove every line from the cart."""
    cart = get_cart(db, user)
    for item in list(cart.items):
        db.delete(item)
    db.commit()
    db.refresh(cart)
    return cart


def cart_totals(cart: Cart) -> tuple[Decimal, int]:
    """Return ``(total_amount, total_items)`` computed from product prices."""
    total = Decimal("0.00")
    count = 0
    for item in cart.items:
        total += to_decimal(item.product.price) * item.quantity
        count += item.quantity
    return total, count


def _item_schema(item: CartItem) -> CartItemOut:
    unit_price = to_decimal(item.product.price)
    return CartItemOut(
        id=item.id,
        product_id=item.product_id,
        product_name=item.product.name,
        unit_price=float(unit_price),
        quantity=item.quantity,
        subtotal=float(unit_price * item.quantity),
        available_stock=item.product.stock,
        in_stock=item.product.stock >= item.quantity,
    )


def to_schema(cart: Cart) -> CartOut:
    """Build the API representation of ``cart``, including calculated totals."""
    total, count = cart_totals(cart)
    return CartOut(
        id=cart.id,
        user_id=cart.user_id,
        items=[_item_schema(item) for item in cart.items],
        total_items=count,
        total_amount=float(total),
        created_at=cart.created_at,
        updated_at=cart.updated_at,
    )
