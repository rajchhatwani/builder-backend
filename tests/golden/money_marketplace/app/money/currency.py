"""Money maths (generated, pack money.currency). Integers and Decimal only: there is no float in this module,
and a float argument is refused with MoneyError instead of being rounded silently.

* An amount is an integer in the currency's MINOR unit (cents, yen, fils). The ISO 4217 exponent says how many
  decimals the major unit has: JPY 0, USD 2, KWD 3.
* One rounding mode everywhere: ROUND_HALF_EVEN (banker's rounding). It is done in integer arithmetic, so it
  does not depend on the Decimal context.
* `allocate` splits an amount by weights with the largest-remainder method: the parts always sum to the total.
"""

from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction
from math import lcm

ROUNDING = "half_even"

# ISO 4217 code -> decimals of the minor unit
EXPONENTS: dict[str, int] = {'AED': 2,
 'AUD': 2,
 'BGN': 2,
 'BHD': 3,
 'BRL': 2,
 'CAD': 2,
 'CHF': 2,
 'CLP': 0,
 'CNY': 2,
 'CZK': 2,
 'DKK': 2,
 'EUR': 2,
 'GBP': 2,
 'HKD': 2,
 'HUF': 2,
 'IDR': 2,
 'ILS': 2,
 'INR': 2,
 'ISK': 0,
 'JOD': 3,
 'JPY': 0,
 'KRW': 0,
 'KWD': 3,
 'MXN': 2,
 'MYR': 2,
 'NOK': 2,
 'NZD': 2,
 'OMR': 3,
 'PHP': 2,
 'PLN': 2,
 'PYG': 0,
 'RON': 2,
 'RWF': 0,
 'SAR': 2,
 'SEK': 2,
 'SGD': 2,
 'THB': 2,
 'TND': 3,
 'TRY': 2,
 'TWD': 2,
 'UGX': 0,
 'USD': 2,
 'VND': 0,
 'XAF': 0,
 'XOF': 0,
 'XPF': 0,
 'ZAR': 2}


class MoneyError(ValueError):
    """A bad currency, amount or weight."""


def exponent(currency: str) -> int:
    try:
        return EXPONENTS[currency]
    except (KeyError, TypeError):
        raise MoneyError(f"unsupported currency {currency!r}") from None


def _exact(value: object) -> Fraction:
    """An int, a Decimal or a decimal string as an exact fraction. Floats and bools are refused."""
    if isinstance(value, bool) or isinstance(value, float):
        raise MoneyError(f"{type(value).__name__} is not allowed in money maths: use int, Decimal or str")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, str):
        try:
            value = Decimal(value.strip())
        except ArithmeticError:
            raise MoneyError(f"not a decimal number: {value[:40]!r}") from None
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise MoneyError("amount must be finite")
        numerator, denominator = value.as_integer_ratio()
        return Fraction(numerator, denominator)
    raise MoneyError(f"{type(value).__name__} is not allowed in money maths")


def _div_half_even(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded half to even, in integers (denominator > 0)."""
    quotient, remainder = divmod(numerator, denominator)
    twice = 2 * remainder
    if twice > denominator or (twice == denominator and quotient % 2 == 1):
        quotient += 1
    return quotient


def round_half_even_ratio(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded half to even; both ints, denominator > 0."""
    if (
        isinstance(numerator, bool)
        or isinstance(denominator, bool)
        or not isinstance(numerator, int)
        or not isinstance(denominator, int)
        or denominator <= 0
    ):
        raise MoneyError("a ratio needs an int numerator and a positive int denominator")
    return _div_half_even(numerator, denominator)


def round_half_even(value: object) -> int:
    """An int, Decimal or decimal string rounded to a whole number, half to even (0.5 -> 0, 1.5 -> 2, 2.5 -> 2)."""
    exact = _exact(value)
    return _div_half_even(exact.numerator, exact.denominator)


def to_minor(amount: object, currency: str) -> int:
    """A major-unit amount (Decimal, str or int) as integer minor units: to_minor("12.345", "USD") == 1234."""
    exact = _exact(amount) * 10 ** exponent(currency)
    return _div_half_even(exact.numerator, exact.denominator)


def from_minor(minor: int, currency: str) -> Decimal:
    """Integer minor units as an exact Decimal in the major unit: from_minor(1234, "USD") == Decimal("12.34")."""
    if isinstance(minor, bool) or not isinstance(minor, int):
        raise MoneyError("minor units must be an int")
    return Decimal(minor).scaleb(-exponent(currency))


def format_minor(minor: int, currency: str) -> str:
    """"-12.50" for (-1250, "USD"), "1234" for (1234, "JPY"), "0.005" for (5, "KWD"): exact, never rounded."""
    exp = exponent(currency)
    if isinstance(minor, bool) or not isinstance(minor, int):
        raise MoneyError("minor units must be an int")
    sign = "-" if minor < 0 else ""
    digits = str(abs(minor)).rjust(exp + 1, "0")
    if exp == 0:
        return f"{sign}{digits}"
    return f"{sign}{digits[:-exp]}.{digits[-exp:]}"


def apply_rate_bp(minor: int, basis_points: int) -> int:
    """minor * basis_points / 10000, rounded half to even (a tax or fee on an amount)."""
    if isinstance(minor, bool) or not isinstance(minor, int) or isinstance(basis_points, bool) or not isinstance(basis_points, int):
        raise MoneyError("minor units and basis points must be ints")
    return _div_half_even(minor * basis_points, 10_000)


def allocate(total_minor: int, weights: Sequence[object]) -> list[int]:
    """Split `total_minor` by `weights` so the parts sum EXACTLY to the total (largest remainder).

    Every part first gets floor(total * weight / sum); the units left over go one each to the parts with the
    largest fractional remainders, a tie going to the earlier part. A negative total is split as its absolute
    value and negated. Weights are non-negative ints, Decimals or decimal strings and must not all be zero."""
    if isinstance(total_minor, bool) or not isinstance(total_minor, int):
        raise MoneyError("total must be an int of minor units")
    if not weights:
        raise MoneyError("allocate needs at least one weight")
    fractions = [_exact(w) for w in weights]
    if any(w < 0 for w in fractions):
        raise MoneyError("weights must not be negative")
    scale = lcm(*(w.denominator for w in fractions))
    ints = [int(w * scale) for w in fractions]
    whole = sum(ints)
    if whole == 0:
        raise MoneyError("weights must not all be zero")
    magnitude = abs(total_minor)
    floors = [magnitude * w // whole for w in ints]
    remainders = [magnitude * w % whole for w in ints]
    left = magnitude - sum(floors)
    order = sorted(range(len(ints)), key=lambda i: (-remainders[i], i))
    for i in order[:left]:
        floors[i] += 1
    return [-part if total_minor < 0 else part for part in floors]
