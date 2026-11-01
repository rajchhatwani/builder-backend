"""The seed engine is deterministic: same plan -> byte-identical rows; another seed -> other rows; ids and
timestamps never depend on the clock; every value respects the column it fills."""

import ast
import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core import seed_engine as engine
from app.core.generator.context import build_context
from app.core.generator.features.seed.module import definitions, plan_data
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


@pytest.fixture(scope="module")
def spec() -> Spec:
    return Spec.model_validate_json((FIXTURES / "seed_demo.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def defs(spec: Spec) -> dict[str, Any]:
    return definitions(build_context(spec))


@pytest.fixture(scope="module")
def plans(spec: Spec) -> dict[str, Any]:
    return plan_data(build_context(spec))


def test_the_same_plan_twice_is_byte_identical(defs: dict[str, Any], plans: dict[str, Any]) -> None:
    for name, plan in plans.items():
        a = engine.generate(defs, copy.deepcopy(plan))
        b = engine.generate(copy.deepcopy(defs), copy.deepcopy(plan))
        assert engine.canonical_dump(a) == engine.canonical_dump(b)
        assert a.digest() == b.digest() and a.plan_hash == b.plan_hash, name


def test_another_seed_gives_other_values_but_the_same_shape(defs: dict[str, Any], plans: dict[str, Any]) -> None:
    plan = plans["demo"]
    other = {**copy.deepcopy(plan), "seed": plan["seed"] + 1}
    a, b = engine.generate(defs, plan), engine.generate(defs, other)
    assert a.counts() == b.counts()
    assert a.digest() != b.digest()
    invoices_a = [r.values for r in a.rows if r.entity == "Invoice"]
    invoices_b = [r.values for r in b.rows if r.entity == "Invoice"]
    assert [v["amount"] for v in invoices_a] != [v["amount"] for v in invoices_b]
    assert a.plan_hash != b.plan_hash


def test_ids_are_derived_not_random_and_the_plan_hash_follows_the_plan(defs: dict[str, Any], plans: dict[str, Any]) -> None:
    a = engine.generate(defs, plans["demo"])
    ids = [r.id for r in a.all_rows()]
    assert len(ids) == len(set(ids))
    assert all(i.version == 5 for i in ids)  # uuid5, never uuid4
    assert a.rows[0].id == engine.row_id("demo", "customers", 0, 0)
    changed = copy.deepcopy(plans["demo"])
    changed["entities"][0]["count"] += 1
    assert engine.generate(defs, changed).plan_hash != a.plan_hash


def test_a_column_added_to_the_plan_does_not_reshuffle_the_others(defs: dict[str, Any], plans: dict[str, Any]) -> None:
    plan = copy.deepcopy(plans["demo"])
    without = copy.deepcopy(plan)
    customers = next(e for e in without["entities"] if e["entity"] == "Customer")
    customers["fields"] = [f for f in customers["fields"] if f["field"] != "notes"]
    full, partial = engine.generate(defs, plan), engine.generate(defs, without)
    names_full = [r.values["name"] for r in full.rows if r.entity == "Customer"]
    names_partial = [r.values["name"] for r in partial.rows if r.entity == "Customer"]
    assert names_full == names_partial


def test_timestamps_start_at_as_of_and_no_clock_is_read(defs: dict[str, Any], plans: dict[str, Any]) -> None:
    data = engine.generate(defs, plans["demo"])
    first = data.rows[0]
    assert first.values["created_at"] == datetime(2026, 10, 1, tzinfo=UTC)
    assert all(r.values["created_at"] >= datetime(2026, 10, 1, tzinfo=UTC) for r in data.rows)
    source = Path(engine.__file__).read_text(encoding="utf-8")
    banned = {"uuid4", "uuid1", "now(", "utcnow", "today(", "time.time", "os.environ", "import os", "secrets"}
    assert not [b for b in banned if b in source]
    tree = ast.parse(source)
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [n])}
    assert not any(str(m).startswith("app") for m in imported)  # stdlib only: copied into generated projects


def test_rows_respect_tenants_references_uniques_and_states(defs: dict[str, Any], plans: dict[str, Any]) -> None:
    data = engine.generate(defs, plans["dev"])
    assert len(data.tenants) == 3
    tenant_ids = {t.id for t in data.tenants}
    customers = {r.id: r for r in data.rows if r.entity == "Customer"}
    invoices = [r for r in data.rows if r.entity == "Invoice"]
    assert data.counts() == {"Customer": 120, "Invoice": 360}
    assert all(r.values["tenant_id"] in tenant_ids for r in data.rows)
    for inv in invoices:
        parent = customers[inv.values["customer_id"]]
        assert parent.values["tenant_id"] == inv.values["tenant_id"]  # tenants never mix
    assert len({r.values["email"] for r in customers.values()}) == len(customers)
    assert len({r.values["invoice_no"] for r in invoices}) == len(invoices)
    machine = defs["entities"]["Invoice"]["machine"]
    for inv in invoices:
        assert inv.values["status"] in machine["states"]
        assert inv.log[0]["transition"] == "created" and inv.log[0]["to_state"] == machine["initial"]
        assert inv.log[-1]["to_state"] == inv.values["status"]
        for before, after in zip(inv.log, inv.log[1:], strict=False):
            assert after["from_state"] == before["to_state"] and after["at"] > before["at"]
    assert {r.values["status"] for r in invoices} == {"draft", "submitted", "approved", "paid", "rejected"}
    assert all(0 <= float(inv.values["amount"]) <= 900 for inv in invoices)
    assert all(len(inv.values["invoice_no"]) <= 40 for inv in invoices)


def test_every_generator_type_makes_values_of_the_right_python_type() -> None:
    rng = engine.rng_for(1, "p", "E", "f", None, 0)
    assert engine._make({"type": "constant", "value": "2026-01-02"}, "date", rng, 0).isoformat() == "2026-01-02"
    assert engine._make({"type": "one_of", "values": [5]}, "integer", rng, 0) == 5
    assert engine._make({"type": "sequence", "prefix": "A-", "start": 7, "width": 3}, "string", rng, 2) == "A-009"
    assert engine._make({"type": "sequence", "start": 7}, "integer", rng, 2) == 9
    assert 3 <= engine._make({"type": "int_range", "min": 3, "max": 4}, "integer", rng, 0) <= 4
    dec = engine._make({"type": "decimal_range", "min": "1.00", "max": "1.05", "places": 2}, "decimal", rng, 0)
    assert str(dec) in {"1.00", "1.01", "1.02", "1.03", "1.04", "1.05"}
    assert isinstance(engine._make({"type": "decimal_range", "min": "1", "max": "2", "places": 1}, "float", rng, 0), float)
    day = engine._make({"type": "date_range", "min": "2026-01-01", "max": "2026-01-03"}, "datetime", rng, 0)
    assert day.tzinfo is not None and day.year == 2026
    assert engine._make({"type": "bool_ratio", "ratio": 0}, "boolean", rng, 0) is False
    assert engine._make({"type": "bool_ratio", "ratio": 1}, "boolean", rng, 0) is True
    words = engine._make({"type": "words", "min_words": 2, "max_words": 2}, "string", rng, 0)
    assert len(words.split()) == 2 and words[0].isupper()
    assert engine._make({"type": "email", "prefix": "u"}, "string", rng, 4) == "u5@example.test"
    with pytest.raises(engine.SeedError):
        engine._make({"type": "shell"}, "string", rng, 0)


def test_state_paths_follow_the_machine_and_skip_guards() -> None:
    machine = {
        "initial": "a",
        "states": ["a", "b", "c", "d"],
        "transitions": [
            {"name": "ab", "from": ["a"], "to": "b", "auto": False},
            {"name": "bc", "from": ["b"], "to": "c", "auto": True},
        ],
    }
    assert engine.state_path(machine, "a") == []
    assert [t["name"] for t in engine.state_path(machine, "c") or []] == ["ab", "bc"]
    assert engine.state_path(machine, "d") is None
    assert engine.reachable_states(machine) == {"a", "b", "c"}


def test_ordering_puts_referenced_entities_first_and_rejects_loops(defs: dict[str, Any], plans: dict[str, Any]) -> None:
    plan = copy.deepcopy(plans["demo"])
    plan["entities"].reverse()
    assert engine.seed_order(defs, plan) == ["Customer", "Invoice"]
    plan["entities"][1]["fields"].append({"field": "x", "generator": {"type": "reference", "entity": "Invoice"}})
    with pytest.raises(engine.SeedError):
        engine.seed_order(defs, plan)


def test_the_word_list_has_no_surprises() -> None:
    assert len(set(engine.WORDS)) == len(engine.WORDS)
    assert all(w.isalpha() and w.islower() for w in engine.WORDS)
    assert engine.MAX_WORD_LENGTH == max(map(len, engine.WORDS))
    assert uuid.UUID(str(engine.NAMESPACE)) == engine.NAMESPACE
    json.dumps(list(engine.WORDS))
