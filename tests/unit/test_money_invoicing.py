"""CP-5B WP2/WP3: the money pack's invoicing block (D7) with AR/AP aging and payouts.

Spec declaration and validation, emission only when declared (existing goldens untouched), tenant treatment and the
guards in the migration, no float, and the pure generated code executed on hand-computed cases: line totals and
half-even tax, the state machine, invoice numbers, aging buckets (app/money/invoicing/{rules,totals}.py), and the
largest-remainder payout split. Database behaviour (gapless numbers under 8 parallel issues, balanced postings,
overpayment, immutability) is proven by tests/e2e/test_invoicing_stack.py and test_marketplace_payout_stack.py."""

import ast
import json
import sys
import types
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.generator import generate
from app.core.generator.engine import module_registry, pack_registry
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_packs import declared_packs

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _raw(name: str = "money_marketplace") -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _spec(raw: dict[str, Any] | None = None) -> Spec:
    return Spec.model_validate(raw if raw is not None else _raw())


def _codes(raw: dict[str, Any]) -> set[str]:
    return {i.code for i in validate(Spec.model_validate(raw))}


def _invoicing_only(payouts: bool = False) -> dict[str, Any]:
    raw = _raw("money_ledger")
    raw["packs"]["money"]["invoicing"] = {"read_roles": ["admin", "member"], "write_roles": ["admin"], "number_prefix": "B-", "payment_terms_days": 10}
    if payouts:
        raw["packs"]["money"]["invoicing"]["payouts"] = {"commission_bp": 500}
    return raw


# --- the spec ----------------------------------------------------------------------------------------------


def test_invoicing_declarations_are_valid_and_defaults_apply() -> None:
    assert validate(_spec(_invoicing_only())) == []
    assert declared_packs(_spec(_invoicing_only())) == ("money.currency", "money.invoicing", "money.ledger")
    inv = _spec(_invoicing_only()).packs.money.invoicing  # type: ignore[union-attr]
    assert inv is not None
    assert (inv.receivable_account, inv.payable_account, inv.revenue_account, inv.tax_account, inv.cash_account) == (
        "receivables", "payables", "revenue", "tax", "bank",
    )
    assert inv.aging_buckets_days == [30, 60, 90] and inv.payouts is None
    assert validate(_spec(_invoicing_only(payouts=True))) == []


@pytest.mark.parametrize(
    "patch",
    [
        {"overdraft": True},
        {"payment_terms_days": 30.5},
        {"payment_terms_days": "30"},
        {"payment_terms_days": True},
        {"aging_buckets_days": [30, 60.5]},
        {"aging_buckets_days": 30},
        {"payouts": {"commission_bp": 10.5}},
        {"payouts": {"fee": 1}},
        {"payouts": True},
    ],
)
def test_unknown_options_and_non_integers_are_refused_by_the_spec_model(patch: dict[str, Any]) -> None:
    raw = _invoicing_only()
    raw["packs"]["money"]["invoicing"].update(patch)
    with pytest.raises(ValidationError):
        Spec.model_validate(raw)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: r["packs"]["money"].pop("ledger"), "needs_ledger"),
        (lambda r: r["packs"]["money"].pop("currency"), "needs_currency"),
        (lambda r: r.pop("auth"), "needs_auth"),
        (lambda r: r["packs"]["money"]["invoicing"].update(read_roles=["ghost"]), "unknown_role"),
        (lambda r: r["packs"]["money"]["invoicing"].update(write_roles=["ghost"]), "unknown_role"),
        (lambda r: r["packs"]["money"]["invoicing"].update(payment_terms_days=-1), "out_of_range"),
        (lambda r: r["packs"]["money"]["invoicing"].update(payment_terms_days=366), "out_of_range"),
        (lambda r: r["packs"]["money"]["invoicing"].update(number_prefix="A B"), "invalid_prefix"),
        (lambda r: r["packs"]["money"]["invoicing"].update(number_prefix="X" * 13), "invalid_prefix"),
        (lambda r: r["packs"]["money"]["invoicing"].update(receivable_account="has space"), "invalid_account_code"),
        (lambda r: r["packs"]["money"]["invoicing"].update(cash_account=""), "invalid_account_code"),
        (lambda r: r["packs"]["money"]["invoicing"].update(cash_account="receivables"), "duplicate_account_code"),
        (lambda r: r["packs"]["money"]["invoicing"].update(aging_buckets_days=[]), "invalid_buckets"),
        (lambda r: r["packs"]["money"]["invoicing"].update(aging_buckets_days=[60, 30]), "invalid_buckets"),
        (lambda r: r["packs"]["money"]["invoicing"].update(aging_buckets_days=[30, 30]), "invalid_buckets"),
        (lambda r: r["packs"]["money"]["invoicing"].update(aging_buckets_days=[0, 30]), "invalid_buckets"),
        (lambda r: r["packs"]["money"]["invoicing"].update(payouts={"commission_bp": 10_001}), "out_of_range"),
        (lambda r: r["packs"]["money"]["invoicing"].update(payouts={"commission_bp": -1}), "out_of_range"),
        (lambda r: r["packs"]["money"]["invoicing"].update(payouts={"commission_account": "bank"}), "duplicate_account_code"),
        (lambda r: r["packs"]["money"]["invoicing"].update(payouts={"seller_payable_account": "bad code"}), "invalid_account_code"),
    ],
)
def test_invoicing_values_are_validated(mutate: Any, code: str) -> None:
    raw = _invoicing_only()
    mutate(raw)
    assert code in _codes(raw)


def test_invoicing_needs_rbac() -> None:
    raw = _invoicing_only()
    raw["authorization"] = {"model": "abac", "policies": []}
    assert "needs_rbac" in _codes(raw)


# --- emission ----------------------------------------------------------------------------------------------


def test_emission_only_when_declared_and_payouts_only_when_asked() -> None:
    plain = generate(_spec(_raw("money_ledger")))
    assert not [p for p in plain if "invoic" in p or "payout" in p]
    only = generate(_spec(_invoicing_only()))
    names = sorted(p for p in only if "invoic" in p)
    assert names == [
        "alembic/versions/0032_money_invoicing.py",
        "app/money/invoicing/__init__.py",
        "app/money/invoicing/config.py",
        "app/money/invoicing/models.py",
        "app/money/invoicing/posting.py",
        "app/money/invoicing/router.py",
        "app/money/invoicing/rules.py",
        "app/money/invoicing/schemas.py",
        "app/money/invoicing/service.py",
        "app/money/invoicing/totals.py",
    ]
    assert not [p for p in only if "payout" in p] and "money_payouts" not in only["alembic/versions/0032_money_invoicing.py"]
    assert "payouts" not in only["app/main.py"] and "money_payouts" not in only["tests/conftest.py"]
    assert not [p for p in only if "reconciliation" in p]
    # with only the invoicing block the migration chain is 0030 -> 0032 (0031 is not rendered)
    assert 'down_revision: str | None = "0030"' in only["alembic/versions/0032_money_invoicing.py"]
    both = generate(_spec(_invoicing_only(payouts=True)))
    assert "app/money/invoicing/payouts_router.py" in both and "app/money/invoicing/payouts_service.py" in both
    assert "include_router(_payouts_router)" in both["app/main.py"] and "money_payouts" in both["tests/conftest.py"]
    assert "COMMISSION_BP = 500" in both["app/money/invoicing/config.py"]
    full = generate(_spec())
    assert 'down_revision: str | None = "0031"' in full["alembic/versions/0032_money_invoicing.py"]
    for table in ("invoice_counters", "invoices", "invoice_lines", "invoice_payments", "money_payouts"):
        assert table in full["tests/conftest.py"]


def test_routes_roles_and_config_come_from_the_spec() -> None:
    files = generate(_spec())
    router = files["app/money/invoicing/router.py"]
    for route in ('"/aging"', '"/{invoice_id}/issue"', '"/{invoice_id}/payments"', '"/{invoice_id}/void"', '"/{invoice_id}"'):
        assert route in router
    cfg = files["app/money/invoicing/config.py"]
    assert 'NUMBER_PREFIX = "MKT-"' in cfg and "PAYMENT_TERMS_DAYS = 14" in cfg and "AGING_BUCKETS_DAYS: tuple[int, ...] = (30, 60, 90, )" in cfg
    assert 'RECEIVABLE_ACCOUNT = "receivables"' in cfg and "WRITE_ROLES: tuple[str, ...] = ('admin',)" in cfg
    payouts = files["app/money/invoicing/payouts_router.py"]
    assert '"/run"' in payouts and '"/totals"' in payouts
    assert "allocate(net_minor, [commission_bp, 10_000 - commission_bp])" in files["app/money/invoicing/payouts_service.py"]
    assert "FOR UPDATE" in files["app/money/invoicing/service.py"].upper().replace("WITH_FOR_UPDATE", "FOR UPDATE")


def test_the_migration_guards_issued_invoices_and_has_no_truncate_trigger() -> None:
    migration = generate(_spec())["alembic/versions/0032_money_invoicing.py"]
    assert "invoices_guard" in migration and "invoice_lines_guard" in migration and "is issued: its content is immutable" in migration
    assert "uq_invoices_number" in migration and "uq_invoice_counters_kind" in migration and "uq_invoice_payments_idempotency_key" in migration
    assert "uq_money_payouts_invoice_id" in migration and "ck_money_payouts_split" in migration
    assert "sa.BigInteger()" in migration and "sa.Numeric" not in migration and "sa.Float" not in migration
    assert "BEFORE TRUNCATE" not in migration.upper()


def test_tenant_treatment_matches_the_ledger_and_single_tenant_has_none() -> None:
    tenant = generate(_spec())
    for path in ("app/money/invoicing/models.py", "alembic/versions/0032_money_invoicing.py"):
        assert tenant[path].count('"auth_tenants.id"') >= 5 and 'ondelete="RESTRICT"' in tenant[path], path
    assert tenant["app/money/invoicing/service.py"].count("_scoped(") >= 4
    assert tenant["app/money/invoicing/posting.py"].count("tenant") >= 10
    raw = _raw()
    raw["auth"]["multi_tenant"] = False
    for permission in raw["auth"]["permissions"]:
        permission.pop("row_rule", None)
    single = generate(Spec.model_validate(raw))
    for path in ("app/money/invoicing/models.py", "alembic/versions/0032_money_invoicing.py"):
        assert "tenant_id" not in single[path] and "auth_tenants" not in single[path], path
    assert "MULTI_TENANT = False" in single["app/money/invoicing/config.py"]


def test_the_blocks_are_registered_with_their_dependencies() -> None:
    packs = pack_registry()
    assert packs["money.invoicing"].id == "money_invoicing"
    assert {"money_currency", "money_ledger"} <= set(packs["money.invoicing"].depends_on)
    assert module_registry()["money_invoicing"].pack == "money.invoicing"


def test_every_invoicing_file_parses() -> None:
    for path, content in generate(_spec()).items():
        if path.endswith(".py"):
            ast.parse(content, filename=path)


# --- the pure generated code, executed -----------------------------------------------------------------------


def _load(files: dict[str, str], names: list[str]) -> dict[str, types.ModuleType]:
    """Execute generated app/money/... modules under their dotted names (no database, no app wiring)."""
    modules: dict[str, types.ModuleType] = {}
    for dotted in names:
        parent, _, leaf = dotted.rpartition(".")
        module = types.ModuleType(dotted)
        sys.modules[dotted] = module
        if parent in sys.modules:
            setattr(sys.modules[parent], leaf, module)
        modules[leaf] = module
    for dotted in names:
        path = dotted.replace(".", "/") + ".py"
        if path in files:
            exec(compile(files[path], path, "exec"), modules[dotted.rpartition(".")[2]].__dict__)  # noqa: S102
    return modules


@pytest.fixture(scope="module")
def gen() -> types.SimpleNamespace:
    files = generate(_spec())
    names = ["app.money", "app.money.settings", "app.money.currency", "app.money.tax", "app.money.invoicing", "app.money.invoicing.rules", "app.money.invoicing.totals"]
    saved = {n: sys.modules.get(n) for n in names}
    try:
        mods = _load(files, names)
        yield types.SimpleNamespace(**mods)
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def test_line_totals_and_tax_round_half_even_per_line(gen: types.SimpleNamespace) -> None:
    lt = gen.totals.line_total
    # hand computed, 'reduced' = 500 bp: 10 -> 0.5 -> 0 | 30 -> 1.5 -> 2 | 50 -> 2.5 -> 2 | 70 -> 3.5 -> 4
    assert [lt(1, n, "USD", "reduced").tax_minor for n in (10, 30, 50, 70)] == [0, 2, 2, 4]
    assert lt(3, 333, "USD", "standard") == gen.totals.LineTotal(999, 200, "standard", 2000)  # 199.8 -> 200
    assert lt(2, 7, "USD", None) == gen.totals.LineTotal(14, 0, None, 0)
    assert lt(1, 10_001, "USD", "standard").tax_minor == 2000  # 2000.2 -> 2000
    assert lt(1, 12_5, "USD", "zero").tax_minor == 0
    # JPY has no minor unit: the same integer maths
    assert lt(1, 105, "JPY", "reduced").tax_minor == 5 and lt(1, 110, "JPY", "reduced").tax_minor == 6  # 5.25 -> 5, 5.5 -> 6 (even)
    # the invoice tax is the sum of the ROUNDED line taxes: three lines of 10 at 5 % are 0 + 0 + 0, not 1.5 -> 2 on 30
    lines = [lt(1, 10, "USD", "reduced")] * 3
    total = gen.totals.invoice_total(lines)
    assert (total.subtotal_minor, total.tax_minor, total.total_minor) == (30, 0, 30)
    assert gen.currency.apply_rate_bp(30, 500) == 2  # (what a total-based tax would have said)
    mixed = gen.totals.invoice_total([lt(1, 10, "USD", "reduced"), lt(1, 30, "USD", "reduced"), lt(1, 50, "USD", "reduced"), lt(3, 333, "USD", "standard"), lt(2, 7, "USD", None)])
    assert (mixed.subtotal_minor, mixed.tax_minor, mixed.total_minor) == (1103, 204, 1307)


def test_line_totals_refuse_floats_bools_and_unknown_rates(gen: types.SimpleNamespace) -> None:
    for call in (
        lambda: gen.totals.line_total(1.5, 10, "USD", None),
        lambda: gen.totals.line_total(1, 10.5, "USD", None),
        lambda: gen.totals.line_total(True, 10, "USD", None),
        lambda: gen.totals.line_total(1, 10, "USD", "nope"),
        lambda: gen.totals.line_total(1, 10, "XXX", "standard"),
    ):
        with pytest.raises((ValueError, gen.tax.TaxError, gen.currency.MoneyError)):
            call()


def test_state_machine(gen: types.SimpleNamespace) -> None:
    r = gen.rules
    allowed = {
        ("draft", "issued"), ("draft", "void"), ("issued", "partially_paid"), ("issued", "paid"), ("issued", "void"),
        ("partially_paid", "partially_paid"), ("partially_paid", "paid"),
    }
    for old in r.STATUSES:
        for new in r.STATUSES:
            assert r.can_transition(old, new) is ((old, new) in allowed), (old, new)
    assert not r.can_transition("paid", "void") and not r.can_transition("void", "issued") and not r.can_transition("nope", "issued")
    assert r.STATUSES == ("draft", "issued", "partially_paid", "paid", "void")


def test_invoice_numbers(gen: types.SimpleNamespace) -> None:
    r = gen.rules
    assert r.invoice_number("MKT-", "receivable", 1) == "MKT-000001"
    assert r.invoice_number("MKT-", "payable", 42) == "MKT-AP-000042"
    assert r.invoice_number("", "receivable", 1_234_567) == "1234567"
    for bad in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            r.invoice_number("X", "receivable", bad)


def test_aging_bucket_boundaries(gen: types.SimpleNamespace) -> None:
    r = gen.rules
    bounds = (30, 60, 90)
    assert r.bucket_labels(bounds) == ["1-30", "31-60", "61-90", "91+"]
    assert r.bucket_labels((7,)) == ["1-7", "8+"]
    cases = {-5: None, 0: None, 1: 0, 30: 0, 31: 1, 60: 1, 61: 2, 90: 2, 91: 3, 5000: 3}
    for days, index in cases.items():
        assert r.bucket_index(days, bounds) == index, days
    assert r.days_past_due(date(2026, 6, 30), date(2026, 6, 30)) == 0
    assert r.days_past_due(date(2026, 5, 31), date(2026, 6, 30)) == 30
    assert r.days_past_due(date(2026, 7, 5), date(2026, 6, 30)) == -5


def test_aging_report_maths_per_currency(gen: types.SimpleNamespace) -> None:
    as_of = date(2026, 6, 30)
    rows = [
        ("USD", date(2026, 7, 5), 1, 1),
        ("USD", date(2026, 6, 30), 2, 1),
        ("USD", date(2026, 6, 29), 4, 1),
        ("USD", date(2026, 5, 31), 8, 1),  # 30 days
        ("USD", date(2026, 5, 30), 16, 2),  # 31 days
        ("USD", date(2026, 4, 1), 32, 1),  # 91 - 1 = 90 days
        ("USD", date(2026, 3, 31), 64, 1),  # 91 days
        ("EUR", date(2026, 6, 1), 1000, 1),
    ]
    report = gen.rules.age(rows, as_of, (30, 60, 90))
    assert [c["currency"] for c in report] == ["EUR", "USD"]  # sorted
    usd = report[1]
    assert (usd["current_minor"], usd["current_count"]) == (3, 2)
    assert [(b["label"], b["amount_minor"], b["count"]) for b in usd["buckets"]] == [("1-30", 12, 2), ("31-60", 16, 2), ("61-90", 32, 1), ("91+", 64, 1)]
    assert [(b["from_days"], b["to_days"]) for b in usd["buckets"]] == [(1, 30), (31, 60), (61, 90), (91, None)]
    assert (usd["total_minor"], usd["count"]) == (127, 8)
    eur = report[0]
    assert eur["current_minor"] == 0 and [b["amount_minor"] for b in eur["buckets"]] == [1000, 0, 0, 0] and eur["total_minor"] == 1000
    assert gen.rules.age([], as_of, (30,)) == []
    one = gen.rules.age([("USD", date(2026, 6, 20), 5, 1)], as_of, (7,))  # 10 days past due, bounds (7)
    assert [(b["label"], b["amount_minor"]) for b in one[0]["buckets"]] == [("1-7", 0), ("8+", 5)]
    for entry in report:
        assert type(entry["total_minor"]) is int and all(type(b["amount_minor"]) is int for b in entry["buckets"])


def test_payout_split_is_a_single_largest_remainder_allocation(gen: types.SimpleNamespace) -> None:
    allocate = gen.currency.allocate
    # 12.50 % platform commission: weights [1250, 8750]
    assert allocate(10_001, [1250, 8750]) == [1250, 8751]  # 1250.125 / 8750.875: the leftover unit goes to the larger remainder
    assert allocate(5_000, [1250, 8750]) == [625, 4_375]
    assert allocate(3, [1250, 8750]) == [0, 3]
    assert allocate(1, [1250, 8750]) == [0, 1]
    assert allocate(7, [10_000, 0]) == [7, 0] and allocate(7, [0, 10_000]) == [0, 7]
    for net in range(0, 400):
        commission, seller = allocate(net, [1250, 8750])
        assert commission + seller == net and commission >= 0 and seller >= 0
