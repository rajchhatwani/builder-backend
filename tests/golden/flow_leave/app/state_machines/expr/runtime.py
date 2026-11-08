"""Python semantics of the expression language. Standard library only, no eval, no platform imports.

This file is copied byte for byte into generated projects (like authz_engine.py). NULL is None and
every operator follows SQL three-valued logic. Integers are int64 with checked overflow; decimals
are exact; `/` on decimals is the exact quotient rounded half away from zero to 10 places.
"""

from decimal import ROUND_HALF_UP, Context, Decimal
from fractions import Fraction
from typing import Any

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
DECIMAL_SCALE = 10
_CTX = Context(prec=200, rounding=ROUND_HALF_UP)


class ExprOverflow(ArithmeticError):
    pass


def to_decimal(x: int | Decimal | None) -> Decimal | None:
    return None if x is None else Decimal(x)


def check_int(x: int | None) -> int | None:
    if x is not None and not INT64_MIN <= x <= INT64_MAX:
        raise ExprOverflow("bigint out of range")
    return x


# --- three-valued logic
def and3(a: bool | None, b: bool | None) -> bool | None:
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or3(a: bool | None, b: bool | None) -> bool | None:
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not3(a: bool | None) -> bool | None:
    return None if a is None else not a


# --- integers
def iadd(a: int | None, b: int | None) -> int | None:
    return None if a is None or b is None else check_int(a + b)


def isub(a: int | None, b: int | None) -> int | None:
    return None if a is None or b is None else check_int(a - b)


def imul(a: int | None, b: int | None) -> int | None:
    return None if a is None or b is None else check_int(a * b)


def ineg(a: int | None) -> int | None:
    return None if a is None else check_int(-a)


def iabs(a: int | None) -> int | None:
    return None if a is None else check_int(abs(a))


def idiv(a: int | None, b: int | None) -> int | None:
    """Integer quotient truncated toward zero; division by zero is NULL."""
    if a is None or b is None or b == 0:
        return None
    q = abs(a) // abs(b)
    return check_int(q if (a < 0) == (b < 0) else -q)


def imod(a: int | None, b: int | None) -> int | None:
    """Remainder with the sign of the dividend; modulo by zero is NULL."""
    if a is None or b is None or b == 0:
        return None
    r = abs(a) % abs(b)
    return -r if a < 0 else r


# --- decimals
def dadd(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else _CTX.add(a, b)


def dsub(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else _CTX.subtract(a, b)


def dmul(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else _CTX.multiply(a, b)


def dneg(a: Decimal | None) -> Decimal | None:
    return None if a is None else _CTX.minus(a)


def dabs(a: Decimal | None) -> Decimal | None:
    return None if a is None else _CTX.abs(a)


def ddiv(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    """Exact quotient rounded half away from zero to 10 places; division by zero is NULL."""
    if a is None or b is None or b == 0:
        return None
    exact = Fraction(a) / Fraction(b) * 10**DECIMAL_SCALE
    n, d = abs(exact.numerator), exact.denominator
    q = (2 * n + d) // (2 * d)
    return _CTX.scaleb(Decimal(-q if exact < 0 else q), -DECIMAL_SCALE)


def dround(a: Decimal | None, digits: int) -> Decimal | None:
    """Round half away from zero (never Python's banker's round())."""
    if a is None:
        return None
    return _CTX.quantize(a, Decimal(1).scaleb(-digits))


# --- comparison (code-point order for strings, like Postgres COLLATE "C")
def compare(op: str, a: Any, b: Any) -> bool | None:
    if a is None or b is None:
        return None
    if isinstance(a, int) and isinstance(b, Decimal) or isinstance(a, Decimal) and isinstance(b, int):
        a, b = Decimal(a), Decimal(b)
    result: bool
    if op == "==":
        result = a == b
    elif op == "!=":
        result = a != b
    elif op == "<":
        result = a < b
    elif op == "<=":
        result = a <= b
    elif op == ">":
        result = a > b
    else:
        result = a >= b
    return result


def in_list(x: Any, items: list[Any]) -> bool | None:
    if x is None:
        return None
    return any(compare("==", x, item) for item in items)


def coalesce(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None
