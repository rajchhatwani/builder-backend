"""Validation for the `packs` section (Cycle 5 domain packs; money pack: ledger D1, currency D5).
Issues go through `add(path, code, message)`. Nothing here runs anything. Structure (unknown pack or option,
a float where an integer is required) is refused by the spec models (extra=forbid, StrictInt); this module
checks the values and the cross-section rules."""

import re
from collections.abc import Callable

from app.core.spec_models import Spec

Add = Callable[[str, str, str], None]

LEDGER_TABLES = ("ledger_accounts", "ledger_transactions", "ledger_entries")
RECON_TABLES = ("reconciliation_runs", "reconciliation_lines", "reconciliation_matches", "reconciliation_events")
INVOICING_TABLES = ("invoice_counters", "invoices", "invoice_lines", "invoice_payments")
PAYOUT_TABLES = ("money_payouts",)
MAX_CURRENCIES = 50
MAX_TAX_RATES = 50
MAX_TAX_BP = 10_000  # 100 %
_NUMBER_PREFIX = re.compile(r"[A-Za-z0-9_/-]{0,12}")
_ACCOUNT_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,39}")
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


def reconciliation_active(spec: Spec) -> bool:
    return money_active(spec) and spec.packs.money.reconciliation is not None  # type: ignore[union-attr]


def invoicing_active(spec: Spec) -> bool:
    return money_active(spec) and spec.packs.money.invoicing is not None  # type: ignore[union-attr]


def payouts_active(spec: Spec) -> bool:
    return invoicing_active(spec) and spec.packs.money.invoicing.payouts is not None  # type: ignore[union-attr]


def declared_packs(spec: Spec) -> tuple[str, ...]:
    """Dotted ids of the packs the spec declares, sorted: the generator emits exactly these."""
    out = []
    if currency_active(spec):
        out.append("money.currency")
    if ledger_active(spec):
        out.append("money.ledger")
    if reconciliation_active(spec):
        out.append("money.reconciliation")
    if invoicing_active(spec):
        out.append("money.invoicing")
    return tuple(sorted(out))


def check_packs(spec: Spec, add: Add) -> None:
    if not money_active(spec):
        return
    money = spec.packs.money  # type: ignore[union-attr]
    assert money is not None
    if all(getattr(money, part) is None for part in ("ledger", "currency", "reconciliation", "invoicing")):
        add("packs.money", "empty_pack", "packs.money declares no block (ledger, currency, reconciliation, invoicing)")
        return
    currency = money.currency
    if currency is not None:
        _check_currency(spec, add)
    if money.ledger is not None:
        _check_ledger(spec, add)
    if money.reconciliation is not None:
        _check_reconciliation(spec, add)
    if money.invoicing is not None:
        _check_invoicing(spec, add)


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


def _check_needs(spec: Spec, add: Add, p: str, what: str) -> None:
    """Shared rules of the blocks that sit on the ledger: the ledger itself, currency, auth with rbac."""
    money = spec.packs.money  # type: ignore[union-attr]
    assert money is not None
    if money.ledger is None:
        add(p, "needs_ledger", f"{what} needs packs.money.ledger (it reads and posts ledger entries)")
    if money.currency is None:
        add(p, "needs_currency", f"{what} needs packs.money.currency")
    if spec.auth is None or not spec.auth.enabled:
        add(p, "needs_auth", f"{what} needs auth.enabled: every route needs a signed-in caller")
    elif spec.authorization is not None and spec.authorization.model != "rbac":
        add(p, "needs_rbac", f"{what} needs authorization.model rbac (it checks roles, not abac / pbac policies)")


def _check_roles(spec: Spec, add: Add, p: str, block: object, fields: tuple[str, ...]) -> None:
    if spec.auth is None:
        return
    known = {r.name for r in spec.auth.roles}
    for field in fields:
        for role in getattr(block, field):
            if role not in known:
                add(f"{p}.{field}", "unknown_role", f"role {role!r} is not an auth role")


def _check_reconciliation(spec: Spec, add: Add) -> None:
    rec = spec.packs.money.reconciliation  # type: ignore[union-attr]
    assert rec is not None
    p = "packs.money.reconciliation"
    _check_needs(spec, add, p, "reconciliation")
    _check_roles(spec, add, p, rec, ("read_roles", "run_roles"))
    if not 0 <= rec.tolerance_minor <= 10**9:
        add(f"{p}.tolerance_minor", "out_of_range", "0 .. 1000000000 minor units (a larger tolerance pairs unrelated rows)")
    if not 1 <= rec.max_lines <= 10_000:
        add(f"{p}.max_lines", "out_of_range", "1 .. 10000 statement lines per run")


def _check_invoicing(spec: Spec, add: Add) -> None:
    inv = spec.packs.money.invoicing  # type: ignore[union-attr]
    assert inv is not None
    p = "packs.money.invoicing"
    _check_needs(spec, add, p, "invoicing")
    _check_roles(spec, add, p, inv, ("read_roles", "write_roles"))
    if not _NUMBER_PREFIX.fullmatch(inv.number_prefix):
        add(f"{p}.number_prefix", "invalid_prefix", "0..12 characters: letters, digits, - _ / (no spaces)")
    if not 0 <= inv.payment_terms_days <= 365:
        add(f"{p}.payment_terms_days", "out_of_range", "0 .. 365 days")
    codes = {
        "receivable_account": inv.receivable_account,
        "payable_account": inv.payable_account,
        "revenue_account": inv.revenue_account,
        "expense_account": inv.expense_account,
        "tax_account": inv.tax_account,
        "cash_account": inv.cash_account,
    }
    if inv.payouts is not None:
        codes["payouts.seller_payable_account"] = inv.payouts.seller_payable_account
        codes["payouts.commission_account"] = inv.payouts.commission_account
        if not 0 <= inv.payouts.commission_bp <= MAX_TAX_BP:
            add(f"{p}.payouts.commission_bp", "out_of_range", f"0..{MAX_TAX_BP} basis points")
    for name, code in codes.items():
        if not _ACCOUNT_CODE.fullmatch(code):
            add(f"{p}.{name}", "invalid_account_code", "an account code: letters, digits, . _ : - (1..40 characters, starts alphanumeric)")
    if len(set(codes.values())) != len(codes):
        add(p, "duplicate_account_code", "every account code (receivable, payable, revenue, expense, tax, cash, payouts) must differ")
    buckets = inv.aging_buckets_days
    if not 1 <= len(buckets) <= 8 or any(b < 1 or b > 3650 for b in buckets) or buckets != sorted(set(buckets)):
        add(f"{p}.aging_buckets_days", "invalid_buckets", "1..8 strictly increasing day counts, each 1 .. 3650")
