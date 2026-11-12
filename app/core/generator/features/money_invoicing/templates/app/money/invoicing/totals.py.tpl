"""Invoice line totals (generated). Integers only; the tax comes from the D5 tax adapter and is rounded half to
even PER LINE (the invoice tax is the sum of its line taxes), so every printed line adds up to the total."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.money import tax as _tax


@dataclass(frozen=True)
class LineTotal:
    net_minor: int
    tax_minor: int
    rate: str | None
    basis_points: int


@dataclass(frozen=True)
class InvoiceTotal:
    subtotal_minor: int
    tax_minor: int
    total_minor: int


def line_total(quantity: int, unit_price_minor: int, currency: str, rate: str | None) -> LineTotal:
    """quantity * unit price (exact), plus the tax on it for a named rate. Raises tax.TaxError for an unknown rate."""
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (quantity, unit_price_minor)):
        raise ValueError("quantity and unit price must be ints")
    net = quantity * unit_price_minor
    if rate is None:
        return LineTotal(net, 0, None, 0)
    quote = _tax.get_adapter().quote(net, currency, rate)
    return LineTotal(net, quote.tax_minor, rate, quote.basis_points)


def invoice_total(lines: Sequence[LineTotal]) -> InvoiceTotal:
    subtotal = sum(x.net_minor for x in lines)
    tax = sum(x.tax_minor for x in lines)
    return InvoiceTotal(subtotal, tax, subtotal + tax)
