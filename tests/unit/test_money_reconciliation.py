"""CP-5B WP1: the money pack's reconciliation block (D6).

Spec declaration and validation, emission only when declared (existing goldens untouched), tenant treatment and the
guards in the migration, no float in any generated money file, and the matcher (the pure generated
app/money/reconciliation/matcher.py) executed on hand-computed cases. The database behaviour (idempotent import,
one-to-one under 8 parallel matches, close) is proven by tests/e2e/test_reconciliation_stack.py."""

import ast
import json
import random
import re
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


def _only_reconciliation() -> dict[str, Any]:
    raw = _raw("money_ledger")
    raw["packs"]["money"]["reconciliation"] = {"read_roles": ["admin", "member"], "run_roles": ["admin"], "tolerance_minor": 2, "max_lines": 50}
    return raw


# --- the spec ----------------------------------------------------------------------------------------------


def test_the_fixtures_are_valid_and_list_the_new_packs() -> None:
    assert validate(_spec()) == []
    assert declared_packs(_spec()) == ("money.currency", "money.invoicing", "money.ledger", "money.reconciliation")
    assert validate(_spec(_only_reconciliation())) == []
    assert declared_packs(_spec(_only_reconciliation())) == ("money.currency", "money.ledger", "money.reconciliation")


@pytest.mark.parametrize(
    "patch",
    [
        {"overdraft": True},  # unknown option
        {"tolerance_minor": 1.5},  # a float is refused, not rounded
        {"tolerance_minor": "5"},
        {"tolerance_minor": True},
        {"max_lines": 10.0},
        {"read_roles": "admin"},
    ],
)
def test_unknown_options_and_non_integers_are_refused_by_the_spec_model(patch: dict[str, Any]) -> None:
    raw = _only_reconciliation()
    raw["packs"]["money"]["reconciliation"].update(patch)
    with pytest.raises(ValidationError):
        Spec.model_validate(raw)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: r["packs"]["money"].pop("ledger"), "needs_ledger"),
        (lambda r: r["packs"]["money"].pop("currency"), "needs_currency"),
        (lambda r: r.pop("auth"), "needs_auth"),
        (lambda r: r["packs"]["money"]["reconciliation"].update(read_roles=["ghost"]), "unknown_role"),
        (lambda r: r["packs"]["money"]["reconciliation"].update(run_roles=["ghost"]), "unknown_role"),
        (lambda r: r["packs"]["money"]["reconciliation"].update(tolerance_minor=-1), "out_of_range"),
        (lambda r: r["packs"]["money"]["reconciliation"].update(tolerance_minor=2**53), "out_of_range"),
        (lambda r: r["packs"]["money"]["reconciliation"].update(tolerance_minor=10**9 + 1), "out_of_range"),
        (lambda r: r["packs"]["money"]["reconciliation"].update(max_lines=0), "out_of_range"),
        (lambda r: r["packs"]["money"]["reconciliation"].update(max_lines=10_001), "out_of_range"),
    ],
)
def test_reconciliation_values_are_validated(mutate: Any, code: str) -> None:
    raw = _only_reconciliation()
    mutate(raw)
    assert code in _codes(raw)


def test_reconciliation_needs_rbac() -> None:
    raw = _only_reconciliation()
    raw["authorization"] = {"model": "abac", "policies": []}
    assert "needs_rbac" in _codes(raw)


# --- emission: only when declared --------------------------------------------------------------------------


def test_nothing_is_emitted_unless_declared() -> None:
    plain = generate(_spec(_raw("money_ledger")))
    assert not [p for p in plain if "reconciliation" in p or "invoic" in p or "payout" in p]
    assert "reconciliation" not in plain["app/main.py"] and "invoicing" not in plain["app/main.py"]
    assert 'PACKS: tuple[str, ...] = ("money.currency", "money.ledger")' in plain["app/money/__init__.py"]
    only = generate(_spec(_only_reconciliation()))
    assert sorted(p for p in only if "reconciliation" in p) == [
        "alembic/versions/0031_money_reconciliation.py",
        "app/money/reconciliation/__init__.py",
        "app/money/reconciliation/config.py",
        "app/money/reconciliation/matcher.py",
        "app/money/reconciliation/models.py",
        "app/money/reconciliation/router.py",
        "app/money/reconciliation/schemas.py",
        "app/money/reconciliation/service.py",
    ]
    assert not [p for p in only if "invoic" in p]
    assert "include_router(_reconciliation_router)" in only["app/main.py"] and "_reconciliation_models" in only["app/models/__init__.py"]
    for table in ("reconciliation_runs", "reconciliation_lines", "reconciliation_matches", "reconciliation_events"):
        assert table in only["tests/conftest.py"]  # emptied between the project's own tests
    assert 'down_revision: str | None = "0030"' in only["alembic/versions/0031_money_reconciliation.py"]
    cfg = only["app/money/reconciliation/config.py"]
    assert "TOLERANCE_MINOR = 2" in cfg and "MAX_LINES = 50" in cfg and "RUN_ROLES: tuple[str, ...] = ('admin',)" in cfg


def test_every_generated_file_parses_and_money_code_has_no_float() -> None:
    files = generate(_spec())
    for path, content in files.items():
        if path.endswith(".py"):
            ast.parse(content, filename=path)
    for path, content in files.items():
        if not path.endswith(".py") or not (path.startswith("app/money/") or "money_" in path):
            continue
        assert "float(" not in content, path
        assert not re.search(r"(:|->)\s*float\b", content), path
        assert "sa.Float" not in content and "Numeric" not in content, path
        tree = ast.parse(content)
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, float)], path
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "float"], path


def test_the_migration_puts_one_to_one_and_the_closed_run_guard_in_the_database() -> None:
    migration = generate(_spec())["alembic/versions/0031_money_reconciliation.py"]
    assert 'sa.UniqueConstraint("entry_id", name="uq_reconciliation_matches_entry_id")' in migration
    assert 'sa.UniqueConstraint("line_id", name="uq_reconciliation_matches_line_id")' in migration
    assert 'sa.UniqueConstraint("run_id", "external_id"' in migration and "uq_reconciliation_runs_idempotency_key" in migration
    assert "sa.BigInteger()" in migration and "sa.Numeric" not in migration and "sa.Float" not in migration
    assert "reconciliation_closed_run_guard" in migration and "reconciliation_events_append_only" in migration
    assert "BEFORE TRUNCATE" not in migration.upper()  # no TRUNCATE guard that the generated tests' TRUNCATE ... CASCADE could trip


def test_tenant_treatment_matches_the_ledger_and_single_tenant_has_none() -> None:
    tenant = generate(_spec())
    for path in ("app/money/reconciliation/models.py", "alembic/versions/0031_money_reconciliation.py"):
        assert tenant[path].count('"auth_tenants.id"') >= 4 and 'ondelete="RESTRICT"' in tenant[path], path
    service = tenant["app/money/reconciliation/service.py"]
    assert service.count("_scoped(") >= 8 and "def tenant_of" in service and "on_conflict_do_nothing" in service
    raw = _raw()
    raw["auth"]["multi_tenant"] = False
    for permission in raw["auth"]["permissions"]:
        permission.pop("row_rule", None)
    single = generate(Spec.model_validate(raw))
    for path in ("app/money/reconciliation/models.py", "alembic/versions/0031_money_reconciliation.py"):
        assert "tenant_id" not in single[path] and "auth_tenants" not in single[path], path
    assert "MULTI_TENANT = False" in single["app/money/reconciliation/config.py"]


def test_the_blocks_are_registered_with_their_dependencies() -> None:
    packs = pack_registry()
    assert sorted(packs) == [
        "ai.agents", "ai.documents", "ai.evals", "ai.gateway", "ai.knowledge", "booking", "money.currency", "money.invoicing", "money.ledger", "money.reconciliation",
        "operations.geo", "operations.location", "operations.matching", "operations.prediction",
    ]
    assert packs["money.reconciliation"].id == "money_reconciliation"
    assert {"money_currency", "money_ledger"} <= set(packs["money.reconciliation"].depends_on)
    assert module_registry()["money_reconciliation"].pack == "money.reconciliation"


# --- the matcher, executed from the generated source ---------------------------------------------------------


@pytest.fixture(scope="module")
def m() -> types.ModuleType:
    source = generate(_spec())["app/money/reconciliation/matcher.py"]
    module = types.ModuleType("matcher_under_test")
    sys.modules["matcher_under_test"] = module  # dataclasses look the module up by name
    exec(compile(source, "matcher.py", "exec"), module.__dict__)  # noqa: S102
    return module


def item(m: types.ModuleType, ident: str, day: str, amount: int, ref: str | None, order: int) -> Any:
    return m.Item(ident, date.fromisoformat(day), amount, ref, order)


def pairs(result: list[Any]) -> list[tuple[str, str, str, int]]:
    return [(p.line_id, p.entry_id, p.method, p.diff_minor) for p in result]


def test_exact_amount_and_the_nearest_date_win(m: types.ModuleType) -> None:
    lines = [item(m, "L1", "2026-03-10", 500, None, 1)]
    entries = [
        item(m, "far", "2026-03-01", 500, None, 0),
        item(m, "near", "2026-03-09", 500, None, 1),
        item(m, "after", "2026-03-13", 500, None, 2),
    ]
    assert pairs(m.match(lines, entries)) == [("L1", "near", "exact", 0)]
    # equal distance (2 days before / 2 days after): the earlier ledger order wins, deterministically
    tie = [item(m, "before", "2026-03-08", 500, None, 0), item(m, "later", "2026-03-12", 500, None, 1)]
    assert pairs(m.match(lines, tie)) == [("L1", "before", "exact", 0)]


def test_a_matching_reference_beats_a_nearer_date_and_an_earlier_entry(m: types.ModuleType) -> None:
    lines = [item(m, "L1", "2026-03-10", 1000, "WANTED", 1)]
    entries = [item(m, "e1", "2026-03-10", 1000, "OTHER", 0), item(m, "e2", "2026-03-01", 1000, "WANTED", 1)]
    assert pairs(m.match(lines, entries)) == [("L1", "e2", "exact_reference", 0)]
    # a reference never makes a different amount match, and an empty reference is not a reference
    assert m.match([item(m, "L", "2026-03-10", 1001, "WANTED", 1)], entries) == []
    blank = [item(m, "L", "2026-03-10", 1000, "", 1)]
    assert pairs(m.match(blank, [item(m, "x", "2026-03-10", 1000, "", 0)])) == [("L", "x", "exact", 0)]


def test_reference_matches_are_made_before_exact_ones_across_all_lines(m: types.ModuleType) -> None:
    # L1 (earlier date, no reference) would take e1 in a single pass; L2 owns e1 by reference
    lines = [item(m, "L1", "2026-03-01", 700, None, 1), item(m, "L2", "2026-03-02", 700, "R", 2)]
    entries = [item(m, "e1", "2026-03-01", 700, "R", 0), item(m, "e2", "2026-03-05", 700, None, 1)]
    assert pairs(m.match(lines, entries)) == [("L1", "e2", "exact", 0), ("L2", "e1", "exact_reference", 0)]


def test_tolerance_picks_the_smallest_difference_then_the_nearest_date(m: types.ModuleType) -> None:
    lines = [item(m, "L1", "2026-03-10", 1000, None, 1)]
    entries = [item(m, "d4", "2026-03-10", 1004, None, 0), item(m, "d2", "2026-03-01", 998, None, 1), item(m, "d2b", "2026-03-09", 1002, None, 2)]
    assert pairs(m.match(lines, entries, 5)) == [("L1", "d2b", "tolerance", -2)]
    assert m.match(lines, entries, 1) == []  # nothing within 1
    assert pairs(m.match(lines, [item(m, "edge", "2026-03-10", 995, None, 0)], 5)) == [("L1", "edge", "tolerance", 5)]  # the edge is inside
    assert m.match(lines, [item(m, "out", "2026-03-10", 994, None, 0)], 5) == []
    assert m.match(lines, [item(m, "x", "2026-03-10", 1001, None, 0)], 0) == []  # tolerance 0 means exact only
    # an exact amount is always preferred to a tolerant one, whatever the order
    mixed = [item(m, "close", "2026-03-10", 1001, None, 0), item(m, "exact", "2026-03-20", 1000, None, 1)]
    assert pairs(m.match(lines, mixed, 5)) == [("L1", "exact", "exact", 0)]


def test_matching_is_one_to_one_and_negative_amounts_work(m: types.ModuleType) -> None:
    lines = [item(m, f"L{n}", "2026-03-10", -250, None, n) for n in range(1, 4)]
    entries = [item(m, f"e{n}", "2026-03-10", -250, None, n) for n in range(2)]
    result = m.match(lines, entries)
    assert len(result) == 2 and len({p.entry_id for p in result}) == 2 and len({p.line_id for p in result}) == 2
    assert [p.line_id for p in result] == ["L1", "L2"]  # earlier statement lines are served first
    assert m.match([], entries) == [] and m.match(lines, []) == []


def test_matching_is_deterministic_whatever_the_input_order(m: types.ModuleType) -> None:
    rng = random.Random(77)
    base_lines = [item(m, f"L{n}", f"2026-03-{1 + n % 20:02d}", rng.choice([100, 200, 300, 301, 99]), rng.choice([None, "A", "B"]), n) for n in range(30)]
    base_entries = [item(m, f"e{n}", f"2026-03-{1 + (n * 7) % 25:02d}", rng.choice([100, 200, 300, 302, 98]), rng.choice([None, "A", "B"]), n) for n in range(30)]
    first = pairs(m.match(base_lines, base_entries, 2))
    for _ in range(5):
        lines, entries = base_lines[:], base_entries[:]
        rng.shuffle(lines)
        rng.shuffle(entries)
        assert pairs(m.match(lines, entries, 2)) == first
    assert len({p[1] for p in first}) == len(first) == len({p[0] for p in first})  # one-to-one


def test_the_matcher_refuses_a_bad_tolerance_and_never_produces_a_float(m: types.ModuleType) -> None:
    for bad in (-1, True, 1.5, "5"):
        with pytest.raises(ValueError):
            m.match([], [], bad)
    result = m.match([item(m, "L", "2026-03-10", 10, None, 1)], [item(m, "e", "2026-03-10", 13, None, 0)], 3)
    assert type(result[0].diff_minor) is int and result[0].diff_minor == -3


def test_the_tolerance_pass_is_fast_on_a_large_input_and_gives_the_same_pairs(m: types.ModuleType) -> None:
    import time

    def reference(lines: list[Any], entries: list[Any], tol: int) -> list[tuple[str, str, int]]:
        """The old O(lines x entries) tolerance pass, on inputs that have no exact matches."""
        used: set[str] = set()
        out = []
        for line in sorted(lines, key=lambda x: (x.day, x.order, x.id)):
            close = [e for e in entries if e.id not in used and abs(e.amount - line.amount) <= tol]
            if close:
                e = min(close, key=lambda e: (abs(e.amount - line.amount), abs((e.day - line.day).days), e.order))
                used.add(e.id)
                out.append((line.id, e.id, line.amount - e.amount))
        return out

    rng = random.Random(5)
    small_lines = [item(m, f"L{n}", f"2026-03-{1 + n % 28:02d}", 10 * rng.randint(1, 60) + 3, None, n) for n in range(60)]
    small_entries = [item(m, f"e{n}", f"2026-03-{1 + (n * 3) % 28:02d}", 10 * rng.randint(1, 60), None, n) for n in range(60)]
    got = [(p.line_id, p.entry_id, p.diff_minor) for p in m.match(small_lines, small_entries, 5)]
    assert got == reference(small_lines, small_entries, 5)
    lines = [item(m, f"L{n}", "2026-03-10", 3 + 10 * n, None, n) for n in range(10_000)]  # never within 5 of an entry
    entries = [item(m, f"e{n}", "2026-03-10", 10 * n + 100_000_000, None, n) for n in range(5_000)]
    start = time.perf_counter()
    assert m.match(lines, entries, 5) == []
    assert time.perf_counter() - start < 1.0
