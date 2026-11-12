"""Validation for the `packs` section (Cycle 5 domain packs; money pack: ledger D1, currency D5).
Issues go through `add(path, code, message)`. Nothing here runs anything. Structure (unknown pack or option,
a float where an integer is required) is refused by the spec models (extra=forbid, StrictInt); this module
checks the values and the cross-section rules."""

import re
from collections.abc import Callable

from app.core.spec_models import Spec

Add = Callable[[str, str, str], None]

LEDGER_TABLES = ("ledger_accounts", "ledger_transactions", "ledger_entries")
MAX_CURRENCIES = 50
MAX_TAX_RATES = 50
MAX_TAX_BP = 10_000  # 100 %
_RATE_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")

# ISO 4217 code -> decimals of the minor unit. Separate from app/core/currencies.py (the payments table,
# which leaves out three-decimal currencies on purpose): the ledger only stores and adds integers, so
# exponents 0, 2 and 3 are all safe here.
MONEY_EXPONENTS: dict[str, int] = {
    **{c: 0 for c in ("CLP", "ISK", "JPY", "KRW", "PYG", "RWF", "UGX", "VND", "XAF", "XOF", "XPF")},
    **{
        c: 2
        for c in (
            "AED", "AUD", "BGN", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF",
            "IDR", "ILS", "INR", "MXN", "MYR", "NOK", "NZD", "PHP", "PLN", "RON", "SAR", "SEK", "SGD",
            "THB", "TRY", "TWD", "USD", "ZAR",
        )
    },
    **{c: 3 for c in ("BHD", "JOD", "KWD", "OMR", "TND")},
}


def money_active(spec: Spec) -> bool:
    return spec.packs is not None and spec.packs.money is not None


def ledger_active(spec: Spec) -> bool:
    return money_active(spec) and spec.packs.money.ledger is not None  # type: ignore[union-attr]


def currency_active(spec: Spec) -> bool:
    return money_active(spec) and spec.packs.money.currency is not None  # type: ignore[union-attr]


def declared_packs(spec: Spec) -> tuple[str, ...]:
    """Dotted ids of the packs the spec declares, sorted: the generator emits exactly these."""
    out = []
    if currency_active(spec):
        out.append("money.currency")
    if ledger_active(spec):
        out.append("money.ledger")
    return tuple(sorted(out))


def check_packs(spec: Spec, add: Add) -> None:
    if not money_active(spec):
        return
    money = spec.packs.money  # type: ignore[union-attr]
    assert money is not None
    if money.ledger is None and money.currency is None:
        add("packs.money", "empty_pack", "packs.money declares neither `ledger` nor `currency`")
        return
    currency = money.currency
    if currency is not None:
        _check_currency(spec, add)
    if money.ledger is not None:
        _check_ledger(spec, add)


def _check_currency(spec: Spec, add: Add) -> None:
    cur = spec.packs.money.currency  # type: ignore[union-attr]
    assert cur is not None
    p = "packs.money.currency"
    if not cur.currencies:
        add(f"{p}.currencies", "empty", "list at least one currency")
    if len(cur.currencies) > MAX_CURRENCIES:
        add(f"{p}.currencies", "too_many", f"at most {MAX_CURRENCIES} currencies")
    if len(set(cur.currencies)) != len(cur.currencies):
        add(f"{p}.currencies", "duplicate", "a currency is listed twice")
    for i, code in enumerate(cur.currencies):
        if code not in MONEY_EXPONENTS:
            add(f"{p}.currencies[{i}]", "unsupported_currency", f"{code!r} is not a supported ISO 4217 code (upper case)")
    if cur.rounding != "half_even":
        add(f"{p}.rounding", "unsupported_rounding", "the only rounding mode is 'half_even' (banker's rounding)")
    if cur.tax is not None:
        if len(cur.tax.rates_bp) > MAX_TAX_RATES:
            add(f"{p}.tax.rates_bp", "too_many", f"at most {MAX_TAX_RATES} tax rates")
        for name, bp in cur.tax.rates_bp.items():
            if not _RATE_NAME.fullmatch(name):
                add(f"{p}.tax.rates_bp.{name[:40]}", "invalid_identifier", "a rate name is lower case letters, digits and _")
            if not 0 <= bp <= MAX_TAX_BP:
                add(f"{p}.tax.rates_bp.{name[:40]}", "out_of_range", f"a rate is 0..{MAX_TAX_BP} basis points")


def _check_ledger(spec: Spec, add: Add) -> None:
    ledger = spec.packs.money.ledger  # type: ignore[union-attr]
    assert ledger is not None
    p = "packs.money.ledger"
    if spec.packs.money.currency is None:  # type: ignore[union-attr]
        add(p, "needs_currency", "the ledger needs packs.money.currency (its currencies and exponents)")
    if spec.auth is None or not spec.auth.enabled:
        add(p, "needs_auth", "the ledger needs auth.enabled: every route needs a signed-in caller")
    elif spec.authorization is not None and spec.authorization.model != "rbac":
        add(p, "needs_rbac", "the ledger needs authorization.model rbac (it checks roles, not abac / pbac policies)")
    if spec.auth is not None:
        known = {r.name for r in spec.auth.roles}
        for field in ("read_roles", "post_roles"):
            for role in getattr(ledger, field):
                if role not in known:
                    add(f"{p}.{field}", "unknown_role", f"role {role!r} is not an auth role")
    if not 1 <= ledger.max_amount_minor <= 2**53 - 1:
        add(f"{p}.max_amount_minor", "out_of_range", "1 .. 2**53-1 (larger integers are not exact in a browser)")
    if not 2 <= ledger.max_entries <= 1000:
        add(f"{p}.max_entries", "out_of_range", "2 .. 1000 lines per transaction")
