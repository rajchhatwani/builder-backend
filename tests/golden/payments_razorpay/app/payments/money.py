"""Money handling (generated): integer minor units and ISO 4217 codes, never floats.

The payable row stores an amount in major units (19.99). A payment needs minor units (1999). The
conversion is exact or it fails: an amount with more decimals than the currency has (19.999 USD,
19.5 JPY) is refused instead of rounded, because rounding silently changes what a customer pays.
"""

from decimal import Decimal, InvalidOperation

from app.core.errors import AppError
from app.payments import config


def normalise_currency(value: object) -> str:
    code = str(value).strip().upper() if value is not None else ""
    if code not in config.EXPONENTS:
        raise AppError("currency_not_allowed", "this currency cannot be paid in this system", 422)
    return code


def to_minor(amount: object, currency: str) -> int:
    """Convert a major-unit amount to minor units, exactly."""
    code = normalise_currency(currency)
    try:
        value = Decimal(str(amount))
    except InvalidOperation as exc:
        raise AppError("amount_invalid", "the amount is not a number", 422) from exc
    if not value.is_finite():
        raise AppError("amount_invalid", "the amount is not a number", 422)
    scaled = value * (Decimal(10) ** config.EXPONENTS[code])
    if scaled != scaled.to_integral_value():
        raise AppError(
            "amount_not_representable",
            f"the amount has more decimal places than {code} allows",
            422,
        )
    minor = int(scaled)
    if minor < 1 or minor > config.MAX_AMOUNT_MINOR:
        raise AppError("amount_out_of_range", "the amount is outside the allowed range", 422)
    return minor


def to_major(minor: int, currency: str) -> Decimal:
    code = normalise_currency(currency)
    return Decimal(minor).scaleb(-config.EXPONENTS[code])
