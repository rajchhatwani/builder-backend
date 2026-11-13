"""CP-5A: the pack framework and the money pack (D1 ledger generated code, D5 currency/tax).

Spec declaration and validation, emission only when declared (packless specs render exactly as before), tenant
treatment, the database guards present in the migration, no float in any money file, and the rounding goldens
(tests/golden/money_rounding.json) run against the GENERATED app/money code."""

import ast
import json
import random
import re
import sys
import types
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.generator import generate
from app.core.generator.engine import default_modules, module_registry, pack_registry
from app.core.spec_models import Spec, spec_hash
from app.core.validation import validate
from app.core.validation_packs import MONEY_EXPONENTS, declared_packs

TESTS = Path(__file__).resolve().parent.parent
FIXTURES = TESTS / "fixtures" / "specs"
ROUNDING = json.loads((TESTS / "golden" / "money_rounding.json").read_text(encoding="utf-8"))


def _raw(name: str = "money_ledger") -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _spec(raw: dict[str, Any] | None = None) -> Spec:
    return Spec.model_validate(raw if raw is not None else _raw())


def _codes(raw: dict[str, Any]) -> set[str]:
    return {i.code for i in validate(Spec.model_validate(raw))}


def _money_files(files: dict[str, str]) -> dict[str, str]:
    return {p: c for p, c in files.items() if p.startswith("app/money/") or "money_" in p}


# --- the spec: strict structure, validated values ----------------------------------------------------------


def test_the_example_spec_is_valid_and_lists_its_packs() -> None:
    spec = _spec()
    assert validate(spec) == []
    assert declared_packs(spec) == ("money.currency", "money.ledger")


@pytest.mark.parametrize(
    ("patch", "loc"),
    [
        ({"packs": {"fintech": {}}}, ("packs", "fintech")),  # unknown pack
        ({"packs": {"money": {"wallet": {}}}}, ("packs", "money", "wallet")),  # unknown part of the pack
        ({"packs": {"money": {"ledger": {"overdraft": True}}}}, ("packs", "money", "ledger", "overdraft")),
        ({"packs": {"money": {"currency": {"mode": "x"}}}}, ("packs", "money", "currency", "mode")),
        ({"packs": {"money": {"currency": {"tax": {"rates": {}}}}}}, ("packs", "money", "currency", "tax", "rates")),
    ],
)
def test_unknown_packs_and_options_are_refused(patch: dict[str, Any], loc: tuple[str, ...]) -> None:
    raw = _raw()
    raw["packs"] = patch["packs"]
    with pytest.raises(ValidationError) as err:
        Spec.model_validate(raw)
    assert any(e["type"] == "extra_forbidden" and tuple(e["loc"]) == loc for e in err.value.errors()), err.value.errors()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["currency"]["tax"]["rates_bp"].update(standard=20.5),  # a float rate
        lambda p: p["currency"]["tax"]["rates_bp"].update(standard="20"),
        lambda p: p["currency"]["tax"]["rates_bp"].update(standard=True),
        lambda p: p["ledger"].update(max_amount_minor=100.0),
        lambda p: p["ledger"].update(max_entries=2.5),
        lambda p: p["currency"].update(currencies="USD"),
    ],
)
def test_floats_and_wrong_types_are_refused_by_the_spec_models(mutate: Any) -> None:
    raw = _raw()
    mutate(raw["packs"]["money"])
    with pytest.raises(ValidationError):
        Spec.model_validate(raw)


def _with(mutate: Any, base: str = "money_ledger") -> dict[str, Any]:
    raw = _raw(base)
    mutate(raw)
    return raw


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: r["packs"]["money"].pop("currency"), "needs_currency"),
        (lambda r: r.pop("auth"), "needs_auth"),
        (lambda r: r["packs"]["money"]["ledger"].update(read_roles=["ghost"]), "unknown_role"),
        (lambda r: r["packs"]["money"]["ledger"].update(post_roles=["ghost"]), "unknown_role"),
        (lambda r: r["packs"]["money"]["ledger"].update(max_amount_minor=2**53), "out_of_range"),
        (lambda r: r["packs"]["money"]["ledger"].update(max_entries=1), "out_of_range"),
        (lambda r: r["packs"]["money"]["currency"].update(currencies=["USD", "XXX"]), "unsupported_currency"),
        (lambda r: r["packs"]["money"]["currency"].update(currencies=["usd"]), "unsupported_currency"),
        (lambda r: r["packs"]["money"]["currency"].update(currencies=["USD", "USD"]), "duplicate"),
        (lambda r: r["packs"]["money"]["currency"].update(currencies=[]), "empty"),
        (lambda r: r["packs"]["money"]["currency"].update(rounding="half_up"), "unsupported_rounding"),
        (lambda r: r["packs"]["money"]["currency"]["tax"]["rates_bp"].update(bad=10_001), "out_of_range"),
        (lambda r: r["packs"]["money"]["currency"]["tax"]["rates_bp"].update(Bad=1), "invalid_identifier"),
        (lambda r: r["packs"]["money"].update(ledger=None, currency=None), "empty_pack"),
    ],
)
def test_pack_values_are_validated(mutate: Any, code: str) -> None:
    assert code in _codes(_with(mutate))


def test_a_ledger_without_rbac_and_a_table_name_clash_are_refused() -> None:
    raw = _raw()
    raw["authorization"] = {"model": "abac", "policies": []}
    assert "needs_rbac" in _codes(raw)
    raw = _raw()
    raw["entities"].append(
        {"name": "LedgerAccount", "table_name": "ledger_accounts", "plural_path": "ledger-accounts", "options": {}, "fields": []}
    )
    assert any(i.code == "duplicate_table" or "ledger_accounts" in i.message for i in validate(Spec.model_validate(raw)))


# --- emission: only when declared; packless specs are untouched ------------------------------------------------


def test_packless_specs_render_no_money_code_and_keep_their_hash() -> None:
    raw = json.loads((FIXTURES / "authz_tenant.json").read_text(encoding="utf-8"))
    spec = Spec.model_validate(raw)
    assert spec.packs is None
    files = generate(spec)
    assert _money_files(files) == {}
    assert not any("ledger" in p for p in files if p.startswith("alembic"))
    assert "_ledger" not in files["app/main.py"] and "ledger" not in files["app/models/__init__.py"]
    assert "packs" not in "".join(files[p] for p in files if p == "tests/conftest.py")
    # hash as computed before the `packs` field existed: dump without it
    dump = spec.model_dump(mode="json")
    dump.pop("packs")
    import hashlib

    legacy = hashlib.sha256(json.dumps(dump, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
    assert spec_hash(spec) == legacy
    # declaring packs does change it
    assert spec_hash(_spec()) != spec_hash(Spec.model_validate({**raw, "packs": {"money": {"currency": {}}}}))


def test_currency_alone_emits_only_the_currency_block() -> None:
    raw = json.loads((FIXTURES / "authz_tenant.json").read_text(encoding="utf-8"))
    raw["packs"] = {"money": {"currency": {"currencies": ["USD", "JPY"]}}}
    files = generate(Spec.model_validate(raw))
    assert sorted(p for p in files if p.startswith("app/money/")) == [
        "app/money/__init__.py",
        "app/money/currency.py",
        "app/money/settings.py",
        "app/money/tax.py",
    ]
    assert 'PACKS: tuple[str, ...] = ("money.currency",)' in files["app/money/__init__.py"]
    assert "ledger" not in files["app/main.py"]


def test_the_ledger_is_wired_in_and_every_file_parses() -> None:
    files = generate(_spec())
    for path, content in files.items():
        if path.endswith(".py"):
            ast.parse(content, filename=path)
    main = files["app/main.py"]
    assert "from app.money.ledger.router import router as _ledger_router" in main and "include_router(_ledger_router)" in main
    assert "_ledger_models" in files["app/models/__init__.py"]
    for table in ("ledger_accounts", "ledger_transactions", "ledger_entries"):
        assert table in files["tests/conftest.py"]  # emptied between the project's own tests
    router = files["app/money/ledger/router.py"]
    for route in ('"/accounts"', '"/transactions"', '"/transactions/{transaction_id}/reverse"', '"/balances"', '"/accounts/{account_id}/entries"'):
        assert route in router
    assert files["app/money/ledger/config.py"].count("('admin', 'member',)") == 2


def test_the_migration_puts_the_invariants_in_the_database() -> None:
    migration = generate(_spec())["alembic/versions/0030_money_ledger.py"]
    assert "sa.BigInteger()" in migration and "sa.Numeric" not in migration and "sa.Float" not in migration
    assert migration.count("DEFERRABLE INITIALLY DEFERRED FOR EACH ROW") == 2  # entries and the header
    assert "CREATE CONSTRAINT TRIGGER ledger_entries_balanced AFTER INSERT ON ledger_entries" in migration
    assert "HAVING sum(amount) <> 0" in migration and "at least two entries" in migration
    assert "BEFORE UPDATE OR DELETE ON {table}" in migration and "ledger_reject_change" in migration
    assert "ledger_entry_same_transaction" in migration and "mixes tenants" in migration
    assert "ck_ledger_entries_amount_nonzero" in migration
    assert "uq_ledger_transactions_reverses_id" in migration and "uq_ledger_transactions_idempotency_key" in migration
    assert '["account_id", "currency"]' in migration  # an entry's currency is pinned to its account's


def test_tenant_treatment_matches_crud_tables_and_single_tenant_has_none() -> None:
    tenant = generate(_spec())
    for path in ("app/money/ledger/models.py", "alembic/versions/0030_money_ledger.py"):
        assert tenant[path].count('"auth_tenants.id"') >= 3 and "ondelete=\"RESTRICT\"" in tenant[path]
    raw = _raw()
    raw["auth"]["multi_tenant"] = False
    for permission in raw["auth"]["permissions"]:
        permission.pop("row_rule", None)
    single = generate(Spec.model_validate(raw))
    for path in ("app/money/ledger/models.py", "alembic/versions/0030_money_ledger.py"):
        assert "tenant_id" not in single[path] and "auth_tenants" not in single[path]
    assert "MULTI_TENANT = False" in single["app/money/ledger/config.py"]
    assert "mixes tenants" not in single["alembic/versions/0030_money_ledger.py"]


def test_the_ledger_scopes_every_query_to_the_callers_tenant() -> None:
    service = generate(_spec())["app/money/ledger/service.py"]
    assert service.count("_scoped(") >= 12 and "def tenant_of" in service
    assert "ON CONFLICT" in service and "on_conflict_do_nothing" in service  # one row per idempotency key
    assert "StrictInt" in generate(_spec())["app/money/ledger/schemas.py"]


@pytest.mark.parametrize("fixture", ["money_ledger", "money_marketplace"])
def test_money_code_has_no_float(fixture: str) -> None:
    """Every generated money file: the ledger, and (marketplace) also reconciliation, invoicing and payouts."""
    money_files = _money_files(generate(_spec(_raw(fixture))))
    if fixture == "money_marketplace":
        assert {"app/money/invoicing/service.py", "app/money/reconciliation/matcher.py", "alembic/versions/0032_money_invoicing.py"} <= set(money_files)
    for path, content in money_files.items():
        if not path.endswith(".py"):
            continue
        assert "float(" not in content, path
        assert not re.search(r"(:|->)\s*float\b", content), path
        assert "sa.Float" not in content and "Numeric" not in content and "Decimal(float" not in content, path
        calls = [n for n in ast.walk(ast.parse(content)) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "float"]
        assert calls == [], path
        tree = ast.parse(content)
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, float)], path


# --- the manifest ------------------------------------------------------------------------------------------------


def test_pack_blocks_are_registered_with_their_dependencies() -> None:
    registry = module_registry()
    packs = pack_registry()
    assert sorted(packs) == [
        "ai.agents", "ai.documents", "ai.evals", "ai.gateway", "ai.knowledge", "booking", "money.currency", "money.invoicing", "money.ledger", "money.reconciliation",
        "operations.geo", "operations.location", "operations.matching", "operations.prediction",
    ]
    assert packs["money.ledger"].id == "money_ledger" and "money_currency" in packs["money.ledger"].depends_on
    assert all(registry[m.id].pack == p for p, m in packs.items())
    assert [m.name for m in default_modules() if m.manifest.pack is not None] == [
        "money_currency",
        "money_ledger",
        "money_reconciliation",
        "money_invoicing",
        "booking",
        "ai_gateway",
        "ai_documents",
        "ai_knowledge",
        "ai_agents",
        "ai_evals",
        "operations_geo",
        "operations_location",
        "operations_matching",
        "operations_prediction",
    ]


# --- the rounding goldens, run against the generated code ----------------------------------------------------------


@pytest.fixture(scope="module")
def money() -> types.SimpleNamespace:
    files = generate(_spec())
    mods: dict[str, types.ModuleType] = {}
    package = types.ModuleType("app.money")
    for name in ("settings", "currency", "tax"):
        module = types.ModuleType(f"app.money.{name}")
        setattr(package, name, module)
        mods[name] = module
    saved = {k: sys.modules.get(k) for k in ("app.money", "app.money.settings", "app.money.currency", "app.money.tax")}
    sys.modules["app.money"] = package
    try:
        for name in ("settings", "currency", "tax"):
            sys.modules[f"app.money.{name}"] = mods[name]
            exec(compile(files[f"app/money/{name}.py"], f"app/money/{name}.py", "exec"), mods[name].__dict__)  # noqa: S102
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
    return types.SimpleNamespace(**mods)


def test_exponents_are_iso_and_match_the_validation_table(money: types.SimpleNamespace) -> None:
    assert money.currency.EXPONENTS == MONEY_EXPONENTS
    assert (money.currency.exponent("JPY"), money.currency.exponent("USD"), money.currency.exponent("KWD")) == (0, 2, 3)
    with pytest.raises(money.currency.MoneyError):
        money.currency.exponent("XXX")


def test_rounding_goldens(money: types.SimpleNamespace) -> None:
    c, t = money.currency, money.tax
    for value, expected in ROUNDING["round_half_even"]:
        assert c.round_half_even(value) == expected, value
    for amount, cur, expected in ROUNDING["to_minor"]:
        assert c.to_minor(amount, cur) == expected, (amount, cur)
    for minor, cur, expected in ROUNDING["from_minor"]:
        assert c.from_minor(minor, cur) == Decimal(expected) and str(c.from_minor(minor, cur)) == expected, (minor, cur)
    for minor, cur, expected in ROUNDING["format_minor"]:
        assert c.format_minor(minor, cur) == expected, (minor, cur)
    for minor, bp, expected in ROUNDING["apply_rate_bp"]:
        assert c.apply_rate_bp(minor, bp) == expected, (minor, bp)
    for total, weights, expected in ROUNDING["allocate"]:
        assert c.allocate(total, weights) == expected, (total, weights)
    adapter = t.get_adapter()
    for net, cur, rate, (tax, gross) in ROUNDING["tax_quote"]:
        q = adapter.quote(net, cur, rate)
        assert (q.net_minor, q.tax_minor, q.gross_minor) == (net, tax, gross), (net, rate)
    for gross, cur, rate, (net, tax) in ROUNDING["tax_quote_inclusive"]:
        q = adapter.quote_inclusive(gross, cur, rate)
        assert (q.net_minor, q.tax_minor, q.gross_minor) == (net, tax, gross), (gross, rate)


def test_allocation_always_sums_exactly(money: types.SimpleNamespace) -> None:
    rng = random.Random(5150)
    for _ in range(500):
        total = rng.randint(-10**12, 10**12)
        weights = [rng.randint(0, 1000) for _ in range(rng.randint(1, 9))]
        if not any(weights):
            weights[0] = 1
        parts = money.currency.allocate(total, weights)
        assert sum(parts) == total and len(parts) == len(weights)
        assert all(p == 0 for p, w in zip(parts, weights, strict=True) if w == 0)
        # no part is off from its exact share by a whole unit
        for part, weight in zip(parts, weights, strict=True):
            assert abs(part * sum(weights) - total * weight) < sum(weights)


def test_floats_and_bad_input_are_refused_not_rounded(money: types.SimpleNamespace) -> None:
    c, t = money.currency, money.tax
    for call in (
        lambda: c.to_minor(12.34, "USD"),
        lambda: c.round_half_even(0.5),
        lambda: c.allocate(100, [0.5, 0.5]),
        lambda: c.allocate(100.0, [1, 1]),
        lambda: c.from_minor(1.5, "USD"),
        lambda: c.apply_rate_bp(100, 20.0),
        lambda: c.to_minor(True, "USD"),
        lambda: c.to_minor("abc", "USD"),
        lambda: c.to_minor(Decimal("NaN"), "USD"),
        lambda: c.allocate(100, []),
        lambda: c.allocate(100, [0, 0]),
        lambda: c.allocate(100, [1, -1]),
        lambda: t.get_adapter().quote(100, "USD", "nope"),
        lambda: t.get_adapter().quote(100, "XXX", "standard"),
    ):
        with pytest.raises((c.MoneyError, t.TaxError)):
            call()


def test_the_tax_adapter_reads_only_the_spec_rates(money: types.SimpleNamespace) -> None:
    assert money.settings.TAX_RATES_BP == {"reduced": 500, "standard": 2000, "zero": 0}
    assert money.settings.CURRENCIES == ("EUR", "JPY", "KWD", "USD")
    assert "import" not in "".join(line for line in generate(_spec())["app/money/tax.py"].splitlines() if "requests" in line or "httpx" in line)


def test_the_ledger_refuses_to_reverse_transactions_owned_by_invoicing() -> None:
    service = generate(_spec())["app/money/ledger/service.py"]
    assert 'MANAGED_KEY_PREFIXES = ("invoice:", "payment:", "payout:")' in service
    assert 'startswith(MANAGED_KEY_PREFIXES)' in service and '"managed_transaction"' in service
