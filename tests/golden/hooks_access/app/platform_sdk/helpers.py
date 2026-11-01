"""Small pure helpers for hook bodies (generated). No I/O, no clock, no randomness."""

import re
import unicodedata
from decimal import Decimal


def clamp[T: (int, float, Decimal)](value: T, low: T, high: T) -> T:
    """`value` limited to the range low..high."""
    return max(low, min(high, value))


def pct_diff(actual: Decimal, expected: Decimal) -> Decimal:
    """How far `actual` is from `expected`, in percent of `expected` (absolute; 0 when both are 0)."""
    if expected == 0:
        return Decimal(0) if actual == 0 else Decimal(100)
    return abs(actual - expected) / abs(expected) * 100


def is_blank(text: str | None) -> bool:
    return text is None or text.strip() == ""


def slugify(text: str) -> str:
    """Lowercase ascii words joined by '-'."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
