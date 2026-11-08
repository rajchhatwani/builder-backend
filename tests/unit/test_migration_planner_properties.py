# ruff: noqa: E501
"""B2-9 migration planner: determinism, idempotence and real fixture specs."""

import copy
import json
import random
from pathlib import Path
from typing import Any

import pytest

from app.core.spec_models import Spec
from app.services.migration_planner import Safety, StepKind, plan_migration

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
ALL_FIXTURES = sorted(p.stem for p in FIX.glob("*.json"))


def load(name: str) -> dict[str, Any]:
    return json.loads((FIX / f"{name}.json").read_text())


def shuffled(spec: dict[str, Any], rnd: random.Random) -> dict[str, Any]:
    s = copy.deepcopy(spec)
    rnd.shuffle(s["entities"])
    rnd.shuffle(s["relations"])
    for e in s["entities"]:
        rnd.shuffle(e["fields"])
    return s


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_plan_of_a_spec_against_itself_is_empty(name: str) -> None:
    spec = load(name)
    assert plan_migration(spec, spec).steps == []
    assert plan_migration(Spec.model_validate(spec), spec).is_empty


def first_entity_with_fields(spec: dict[str, Any], n: int = 2) -> dict[str, Any]:
    return next(e for e in spec["entities"] if len(e["fields"]) >= n)


# --- three real old -> new pairs -----------------------------------------------------------
def test_demo_invoice_pair_add_required_drop_widen_new_table() -> None:
    old = load("demo_invoice")
    new = copy.deepcopy(old)
    inv = next(e for e in new["entities"] if e["name"] == "Invoice")
    inv["fields"].append({"name": "cost_center", "type": "string", "required": True})
    inv["fields"] = [f for f in inv["fields"] if f["name"] != "memo"]
    new["entities"].append(
        {"name": "Attachment", "table_name": "attachments", "plural_path": "attachments", "options": {}, "fields": [{"name": "label", "type": "string"}]}
    )
    plan = plan_migration(old, new)
    got = {(s.kind, s.entity, s.field, s.safety) for s in plan.steps}
    assert got == {
        (StepKind.create_table, "Attachment", None, Safety.safe),
        (StepKind.add_column, "Invoice", "cost_center", Safety.backfill),
        (StepKind.drop_column, "Invoice", "memo", Safety.destructive),
    }
    assert not plan.apply_allowed(False) and plan.apply_allowed(True)
    assert plan.steps[0].kind == StepKind.create_table and plan.steps[-1].kind == StepKind.drop_column


def test_blog_pair_relation_changes() -> None:
    old = load("blog")
    new = copy.deepcopy(old)
    removed = new["relations"].pop(0)  # Post -> Comment (cascade, required)
    plan = plan_migration(old, new)
    assert {(s.kind, s.entity, s.safety) for s in plan.steps} == {
        (StepKind.drop_fk, removed["to_entity"], Safety.safe),
        (StepKind.drop_column, removed["to_entity"], Safety.destructive),
    }
    # and back: re-adding the relation on populated tables needs a backfill
    back = plan_migration(new, old)
    assert (StepKind.add_fk, Safety.backfill) in {(s.kind, s.safety) for s in back.steps}
    assert any(s.kind == StepKind.add_column and s.safety == Safety.backfill for s in back.steps)  # required relation


def test_demo_leave_pair_tenancy_and_enum() -> None:
    old = load("demo_leave")
    new = copy.deepcopy(old)
    ent_with_enum = next((e, f) for e in new["entities"] for f in e["fields"] if f["type"] == "enum")
    ent_with_enum[1]["enum_values"] = list(ent_with_enum[1]["enum_values"]) + ["zz_new"]
    plan = plan_migration(old, new)
    assert [(s.kind, s.safety) for s in plan.steps] == [(StepKind.add_enum_value, Safety.safe)]
    new.setdefault("auth", {"enabled": True})
    new["auth"] = {**(new["auth"] or {"enabled": True}), "multi_tenant": True}
    old_mt = (old.get("auth") or {}).get("multi_tenant", False)
    plan2 = plan_migration(old, new)
    if not old_mt:
        tenant = [s for s in plan2.steps if s.kind == StepKind.add_tenant_id]
        assert len(tenant) == len(old["entities"]) and all(s.safety == Safety.backfill for s in tenant)


def test_library_pair_type_changes() -> None:
    old = load("library")
    new = copy.deepcopy(old)
    e = first_entity_with_fields(new)
    f = next(f for f in e["fields"] if f["type"] == "string")
    f["type"] = "integer"
    f.pop("max_length", None)
    plan = plan_migration(old, new)
    step = next(s for s in plan.steps if s.field == f["name"])
    assert (step.kind, step.safety) == (StepKind.convert_type, Safety.backfill)
    assert step.backfill_strategy


# --- determinism ---------------------------------------------------------------------------
PAIRS = [
    ("demo_invoice", "demo_leave"),
    ("blog", "library"),
    ("minimal", "blog"),
    ("blog", "minimal"),
    ("shop_auth", "authz_tenant"),
]


@pytest.mark.parametrize(("a", "b"), PAIRS)
def test_input_order_does_not_change_the_json_bytes(a: str, b: str) -> None:
    old, new = load(a), load(b)
    expected = plan_migration(old, new).to_json()
    assert expected  # non-trivial: unrelated specs differ
    for seed in range(8):
        rnd = random.Random(seed)
        assert plan_migration(shuffled(old, rnd), shuffled(new, rnd)).to_json() == expected


def test_unrelated_specs_produce_both_drop_and_create() -> None:
    plan = plan_migration(load("blog"), load("demo_invoice"))
    kinds = {s.kind for s in plan.steps}
    assert StepKind.create_table in kinds and StepKind.drop_table in kinds
    assert plan.requires_confirmation


def test_repeated_planning_is_byte_identical_and_pydantic_input_equals_dict_input() -> None:
    old, new = load("blog"), load("library")
    first = plan_migration(old, new).to_json()
    assert all(plan_migration(old, new).to_json() == first for _ in range(5))
    assert plan_migration(Spec.model_validate(old), Spec.model_validate(new)).to_json() == first


def test_plan_is_idempotent_and_json_round_trips() -> None:
    old, new = load("blog"), load("demo_invoice")
    plan = plan_migration(old, new)
    again = plan_migration(old, new)
    assert plan == again
    data = json.loads(plan.to_json())
    assert [s["seq"] for s in data["steps"]] == list(range(1, len(plan.steps) + 1))
    assert data["requires_confirmation"] is plan.requires_confirmation
    # applying the plan means the schema equals `new`: planning (new, new) is empty
    assert plan_migration(new, new).steps == []


# --- seeded property test over random mutations --------------------------------------------
TYPES = ["string", "text", "integer", "bigint", "float", "decimal", "boolean", "date", "datetime", "uuid", "json"]


def random_spec(rnd: random.Random) -> dict[str, Any]:
    ents = []
    for i in range(rnd.randint(1, 4)):
        fields = []
        for j in range(rnd.randint(0, 5)):
            t = rnd.choice(TYPES + ["enum"])
            f: dict[str, Any] = {"name": f"f{j}", "type": t, "required": rnd.random() < 0.3, "unique": rnd.random() < 0.2, "indexed": rnd.random() < 0.2}
            if t == "string" and rnd.random() < 0.5:
                f["max_length"] = rnd.choice([10, 50, 255])
            if t == "enum":
                f["enum_values"] = rnd.sample(["a", "b", "c", "d"], rnd.randint(1, 4))
            fields.append(f)
        ents.append({"name": f"E{i}", "table_name": f"e{i}s", "plural_path": f"e{i}s", "options": {"soft_delete": rnd.random() < 0.2}, "fields": fields})
    rels = []
    if len(ents) > 1 and rnd.random() < 0.7:
        rels.append({"kind": rnd.choice(["one_to_many", "one_to_one", "many_to_many"]), "from_entity": "E0", "to_entity": "E1", "from_name": "kids", "to_name": "parent", "on_delete": rnd.choice(["cascade", "restrict", "set_null"]), "required": rnd.random() < 0.5})
    s: dict[str, Any] = {"spec_version": 1, "project": {"name": "R", "slug": "r"}, "entities": ents, "relations": rels}
    if rnd.random() < 0.3:
        s["auth"] = {"enabled": True, "multi_tenant": rnd.random() < 0.5}
    return s


@pytest.mark.parametrize("seed", range(60))
def test_property_self_plan_empty_and_plan_stable(seed: int) -> None:
    rnd = random.Random(seed)
    old, new = random_spec(rnd), random_spec(rnd)
    assert plan_migration(old, old).steps == []
    assert plan_migration(new, new).steps == []
    plan = plan_migration(old, new)
    assert plan.to_json() == plan_migration(copy.deepcopy(old), copy.deepcopy(new)).to_json()
    assert plan.to_json() == plan_migration(shuffled(old, rnd), shuffled(new, rnd)).to_json()
    # invariants of every plan
    phases = [s.phase for s in plan.steps]
    assert phases == sorted(phases)
    assert [s.seq for s in plan.steps] == list(range(1, len(plan.steps) + 1))
    assert plan.requires_confirmation == any(s.safety == Safety.destructive for s in plan.steps)
    assert plan.apply_allowed(True)
    assert plan.apply_allowed(False) == (not plan.requires_confirmation)
    for s in plan.steps:
        assert s.reason
        if s.safety == Safety.backfill:
            assert s.backfill_strategy or s.suggested_action
        if s.safety == Safety.destructive:
            assert s.suggested_action
