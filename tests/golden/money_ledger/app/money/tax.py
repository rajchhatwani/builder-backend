"""A static tax adapter (generated, pack money.currency). No network: rates are data from the spec
(app/money/settings.py, basis points). Swap `get_adapter` for your own TaxAdapter to call a real tax service.

All amounts are integer minor units; the tax is rounded half to even (app/money/currency.py)."""

from dataclasses import dataclass
from typing import Protocol

from app.money import currency, settings


class TaxError(ValueError):
    """An unknown tax rate or a bad amount."""


@dataclass(frozen=True)
class TaxQuote:
    rate: str
    basis_points: int
    net_minor: int
    tax_minor: int
    gross_minor: int


class TaxAdapter(Protocol):
    def quote(self, net_minor: int, currency_code: str, rate: str) -> TaxQuote: ...

    def quote_inclusive(self, gross_minor: int, currency_code: str, rate: str) -> TaxQuote: ...


class StaticTaxAdapter:
    """Looks a named rate up in a fixed table."""

    def __init__(self, rates_bp: dict[str, int]) -> None:
        self._rates = dict(rates_bp)

    def _bp(self, rate: str) -> int:
        try:
            return self._rates[rate]
        except KeyError:
            raise TaxError(f"unknown tax rate {rate!r}") from None

    def quote(self, net_minor: int, currency_code: str, rate: str) -> TaxQuote:
        """Tax on a net (tax-exclusive) amount."""
        currency.exponent(currency_code)  # the currency must be supported
        bp = self._bp(rate)
        tax = currency.apply_rate_bp(net_minor, bp)
        return TaxQuote(rate, bp, net_minor, tax, net_minor + tax)

    def quote_inclusive(self, gross_minor: int, currency_code: str, rate: str) -> TaxQuote:
        """Split a gross (tax-inclusive) amount: net = gross / (1 + rate), tax = gross - net."""
        currency.exponent(currency_code)
        bp = self._bp(rate)
        net = currency.round_half_even_ratio(gross_minor * 10_000, 10_000 + bp)
        return TaxQuote(rate, bp, net, gross_minor - net, gross_minor)


def get_adapter() -> StaticTaxAdapter:
    return StaticTaxAdapter(settings.TAX_RATES_BP)
