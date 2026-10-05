"""Helpers that read values from both Stripe objects and plain dicts.

Stripe returns ``StripeObject`` instances in production, but plain dicts are
much easier to build in tests, so webhook handling works with either.
"""

from __future__ import annotations

from typing import Any


def obj_get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a Stripe object, a dict, or ``None``."""
    if obj is None:
        return default
    value = obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
    return default if value is None else value


def obj_str(obj: Any, key: str, default: str | None = None) -> str | None:
    """Like :func:`obj_get` but coerces the result to ``str | None``."""
    value = obj_get(obj, key)
    return default if value is None else str(value)
