"""Money helpers, currency conversion and the shared ``utcnow`` timestamp."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

#: Currencies Stripe expects in whole units (no minor unit / decimal places).
ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset(
    {
        "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw",
        "mga", "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
    }
)

TWO_DECIMAL_PLACES = Decimal("0.01")
DEFAULT_CURRENCY = "inr"


def utcnow() -> datetime:
    """Timezone-aware "now" (used as the Python-side column default)."""
    return datetime.now(timezone.utc)


def to_decimal(value: Decimal | float | int | str | None) -> Decimal:
    """Coerce any numeric value to a 2dp ``Decimal`` using half-up rounding."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)


def to_float(value: Decimal | float | int | str | None) -> float:
    """Coerce a money value to ``float`` for JSON responses."""
    return float(to_decimal(value))


def to_minor_units(amount: Decimal | float | int | str | None, currency: str | None = None) -> int:
    """Convert a major-unit amount into the integer Stripe expects.

    Zero-decimal currencies (JPY, KRW, ...) must not be multiplied by 100.
    """
    normalised = (currency or DEFAULT_CURRENCY).strip().lower()
    value = to_decimal(amount)
    if normalised in ZERO_DECIMAL_CURRENCIES:
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int(value * 100)


def from_minor_units(amount: int, currency: str | None = None) -> Decimal:
    """Inverse of :func:`to_minor_units` (useful when reading Stripe amounts)."""
    normalised = (currency or DEFAULT_CURRENCY).strip().lower()
    value = Decimal(int(amount))
    if normalised in ZERO_DECIMAL_CURRENCIES:
        return to_decimal(value)
    return to_decimal(value / 100)