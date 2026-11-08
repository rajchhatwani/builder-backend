# ruff: noqa: E501
"""B2-9 migration planner: one table-driven case per safety class and step kind."""

import copy
from typing import Any

import pytest

from app.services.migration_planner import (
    MigrationPlanError,
    Safety,
    StepKind,
    plan_migration,
    render_json,
    render_text,
)


def fld(name: str, type_: str = "string", **kw: Any) -> dict[str, Any]:
    return {"name": name, "type": type_, **kw}


def ent(name: str, fields: list[dict[str, Any]], table: str | None = None, **opts: Any) -> dict[str, Any]:
    t = table or name.lower() + "s"
    return {"name": name, "table_name": t, "plural_path": t, "options": opts, "fields": fields}


def spec(entities: list[dict[str, Any]], relations: list[dict[str, Any]] | None = None, tenant: bool = False) -> dict[str, Any]:
    s: dict[str, Any] = {
        "spec_version": 1,
        "project": {"name": "T", "slug": "t"},
        "entities": entities,
        "relations": relations or [],
    }
    if tenant:
        s["auth"] = {"enabled": True, "multi_tenant": True}
    return s


def rel(kind: str = "one_to_many", frm: str = "Item", to: str = "Part", **kw: Any) -> dict[str, Any]:
    return {"kind": kind, "from_entity": frm, "to_entity": to, "from_name": "parts", "to_name": "item", **kw}


BASE_FIELDS = [
    fld("name", max_length=50, required=True),
    fld("qty", "integer"),
    fld("note", "text"),
    fld("status", "enum", enum_values=["a", "b"]),
]


def base(extra_fields: list[dict[str, Any]] | None = None, **kw: Any) -> dict[str, Any]:
    return spec([ent("Item", BASE_FIELDS + (extra_fields or [])), ent("Part", [fld("label")])], **kw)


def mutate(fields_after: list[dict[str, Any]]) -> dict[str, Any]:
    return spec([ent("Item", fields_after), ent("Part", [fld("label")])])


def replace_field(name: str, **changes: Any) -> dict[str, Any]:
    fields = copy.deepcopy(BASE_FIELDS)
    for f in fields:
        if f["name"] == name:
            f.update(changes)
    return mutate(fields)


def kinds(plan: Any) -> list[tuple[str, str | None, str]]:
    return [(s.kind.value, s.field, s.safety.value) for s in plan.steps]


# (id, new spec, expected (kind, field, safety) list)
CASES = [
    ("add_nullable_column", base([fld("extra")]), [("add_column", "extra", "safe")]),
    ("add_required_with_default", base([fld("extra", "integer", required=True, default=0)]), [("add_column", "extra", "safe")]),
    ("add_index", replace_field("qty", indexed=True), [("add_index", "qty", "safe")]),
    ("widen_int_to_bigint", replace_field("qty", type="bigint"), [("widen_type", "qty", "safe")]),
    ("varchar_growth", replace_field("name", max_length=100), [("widen_type", "name", "safe")]),
    ("varchar_unbounded", replace_field("name", max_length=None), [("widen_type", "name", "safe")]),
    ("relax_not_null", replace_field("name", required=False), [("relax_not_null", "name", "safe")]),
    ("add_enum_value", replace_field("status", enum_values=["a", "b", "c"]), [("add_enum_value", "status", "safe")]),
    ("default_added_optional", replace_field("qty", default=1), [("change_default", "qty", "safe")]),
    ("drop_unique_is_safe", None, [("drop_unique", "name", "safe")]),
    ("add_required_no_default", base([fld("extra", required=True)]), [("add_column", "extra", "backfill")]),
    ("tighten_to_required", replace_field("qty", required=True), [("set_not_null", "qty", "backfill")]),
    ("new_unique", replace_field("qty", unique=True), [("add_unique", "qty", "backfill")]),
    ("string_to_int_cast", replace_field("name", type="integer", max_length=None), [("convert_type", "name", "backfill")]),
    ("drop_column", mutate([f for f in BASE_FIELDS if f["name"] != "note"]), [("drop_column", "note", "destructive")]),
    ("narrow_bigint", None, [("narrow_type", "qty", "destructive")]),
    ("shorten_length", replace_field("name", max_length=10), [("shorten_length", "name", "destructive")]),
    ("drop_enum_value", replace_field("status", enum_values=["a"]), [("drop_enum_value", "status", "destructive")]),
    ("incompatible_type", replace_field("qty", type="boolean"), [("change_type", "qty", "destructive")]),
    ("text_to_string", replace_field("note", type="string", max_length=20), [("narrow_type", "note", "destructive")]),
]


@pytest.mark.parametrize(("case_id", "new", "expected"), CASES, ids=[c[0] for c in CASES])
def test_field_changes_by_class(case_id: str, new: dict[str, Any] | None, expected: list[tuple[str, str, str]]) -> None:
    old = base()
    if case_id == "drop_unique_is_safe":
        old = replace_field("name", unique=True)
        new = base()
    elif case_id == "narrow_bigint":
        old = replace_field("qty", type="bigint")
        new = base()
    assert new is not None
    plan = plan_migration(old, new)
    assert kinds(plan) == expected
    for step in plan.steps:
        assert step.reason
        assert step.entity == "Item"
        assert step.table == "items"


def test_add_table_is_safe_and_creates_first() -> None:
    old = base()
    new = copy.deepcopy(old)
    new["entities"].append(ent("Tag", [fld("label")]))
    plan = plan_migration(old, new)
    assert kinds(plan) == [("create_table", None, "safe")]
    assert "CREATE TABLE" in (plan.steps[0].sql_hint or "")
    assert plan.apply_allowed(False)


def test_drop_table_is_destructive() -> None:
    old = base()
    new = spec([ent("Item", BASE_FIELDS)])
    plan = plan_migration(old, new)
    assert kinds(plan) == [("drop_table", None, "destructive")]
    assert plan.steps[0].entity == "Part"


def test_enum_add_and_remove_in_one_change() -> None:
    plan = plan_migration(base(), replace_field("status", enum_values=["b", "z"]))
    assert {(k, s) for k, _, s in kinds(plan)} == {("add_enum_value", "safe"), ("drop_enum_value", "destructive")}


def test_required_tightening_with_default_strategy_uses_default() -> None:
    plan = plan_migration(base(), replace_field("qty", required=True, default=7))
    step = next(s for s in plan.steps if s.kind == StepKind.set_not_null)
    assert step.safety == Safety.backfill
    assert step.backfill_strategy and "7" in step.backfill_strategy
    assert step.sql_hint and step.sql_hint.index("UPDATE") < step.sql_hint.index("SET NOT NULL")


def test_default_semantic_change_on_required_is_backfill() -> None:
    old = replace_field("qty", required=True, default=1)
    new = replace_field("qty", required=True, default=2)
    plan = plan_migration(old, new)
    assert kinds(plan) == [("change_default", "qty", "backfill")]


def test_backfill_orders_between_additive_and_constraints_and_destructive_last() -> None:
    new_fields = [f for f in BASE_FIELDS if f["name"] != "note"] + [fld("extra", required=True), fld("tag", indexed=True)]
    new_fields[0] = {**new_fields[0], "max_length": 100}
    plan = plan_migration(base(), mutate(new_fields))
    phases = [s.phase for s in plan.steps]
    assert phases == sorted(phases)
    assert plan.steps[-1].kind == StepKind.drop_column
    assert [s.seq for s in plan.steps] == list(range(1, len(plan.steps) + 1))
    assert plan.requires_confirmation and plan.requires_backfill
    assert plan.highest_safety == Safety.destructive


def test_new_unique_on_fresh_nullable_column_is_safe_but_required_one_is_backfill() -> None:
    p1 = plan_migration(base(), base([fld("code", unique=True)]))
    assert kinds(p1) == [("add_column", "code", "safe"), ("add_unique", "code", "safe")]
    p2 = plan_migration(base(), base([fld("code", required=True, default="x", unique=True)]))
    assert ("add_unique", "code", "backfill") in kinds(p2)


def test_new_foreign_key_on_existing_tables_is_backfill() -> None:
    old = base()
    new = base()
    new["relations"] = [rel()]
    plan = plan_migration(old, new)
    assert ("add_fk", "item_id", "backfill") in kinds(plan)
    fk = next(s for s in plan.steps if s.kind == StepKind.add_fk)
    assert fk.backfill_strategy and "orphan" in fk.backfill_strategy
    assert "FOREIGN KEY" in (fk.sql_hint or "")


def test_required_relation_adds_backfill_column() -> None:
    new = base()
    new["relations"] = [rel(required=True)]
    plan = plan_migration(base(), new)
    assert ("add_column", "item_id", "backfill") in kinds(plan)


def test_relation_on_new_table_needs_no_extra_step() -> None:
    old = spec([ent("Item", BASE_FIELDS)])
    new = base()
    new["relations"] = [rel()]
    assert kinds(plan_migration(old, new)) == [("create_table", None, "safe")]


def test_many_to_many_adds_join_table_and_removal_is_destructive() -> None:
    old, new = base(), base()
    new["relations"] = [rel("many_to_many")]
    add = plan_migration(old, new)
    assert kinds(add) == [("create_table", "parts", "safe")]
    assert kinds(plan_migration(new, old)) == [("drop_table", "parts", "destructive")]


def test_removed_relation_is_drop_fk_safe_plus_destructive_column() -> None:
    old = base()
    old["relations"] = [rel()]
    plan = plan_migration(old, base())
    assert sorted(kinds(plan)) == sorted([("drop_fk", "item_id", "safe"), ("drop_column", "item_id", "destructive")])
    assert next(s for s in plan.steps if s.kind == StepKind.drop_fk).note


def test_relation_required_and_on_delete_changes() -> None:
    a, b = base(), base()
    a["relations"] = [rel(on_delete="restrict")]
    b["relations"] = [rel(on_delete="cascade", required=True)]
    assert {(k, s) for k, _, s in kinds(plan_migration(a, b))} == {("set_not_null", "backfill"), ("alter_fk", "safe")}
    assert ("relax_not_null", "item_id", "safe") in kinds(plan_migration(b, a))


def test_soft_delete_toggle() -> None:
    off = base()
    on = base()
    on["entities"][0]["options"] = {"soft_delete": True}
    assert kinds(plan_migration(off, on)) == [("add_column", "deleted_at", "safe")]
    assert kinds(plan_migration(on, off)) == [("drop_column", "deleted_at", "destructive")]


def test_enabling_tenancy_is_backfill_per_existing_table_and_disabling_is_destructive() -> None:
    plan = plan_migration(base(), base(tenant=True))
    assert [(s.kind, s.entity, s.safety) for s in plan.steps] == [
        (StepKind.add_tenant_id, "Item", Safety.backfill),
        (StepKind.add_tenant_id, "Part", Safety.backfill),
    ]
    assert plan.steps[0].backfill_strategy
    off = plan_migration(base(tenant=True), base())
    assert {s.kind for s in off.steps} == {StepKind.drop_tenant_id}
    assert off.requires_confirmation


def test_new_table_under_tenancy_carries_tenant_id_without_backfill() -> None:
    old = base(tenant=True)
    new = copy.deepcopy(old)
    new["entities"].append(ent("Tag", [fld("label")]))
    plan = plan_migration(old, new)
    assert kinds(plan) == [("create_table", None, "safe")]
    assert "tenant_id" in (plan.steps[0].sql_hint or "")


def test_behavior_only_changes_are_ignored() -> None:
    old = base()
    new = copy.deepcopy(old)
    new["state_machines"] = [
        {"entity": "Item", "field": "status", "initial": "a", "transitions": [{"name": "go", "from_states": ["a"], "to_state": "b"}]}
    ]
    new["settings"] = [{"key": "rate", "type": "int", "default": 1}]
    new["entities"][0]["options"] = {"filterable": ["qty"], "default_page_size": 50}
    plan = plan_migration(old, new)
    assert plan.is_empty and plan.apply_allowed(False) and not plan.requires_confirmation
    assert "state_machines" in plan.ignored_sections and "settings" in plan.ignored_sections
    assert "entities" in plan.ignored_sections
    assert "No schema change" in render_text(plan)


def test_empty_diff_gives_empty_plan() -> None:
    plan = plan_migration(base(), base())
    assert plan.steps == [] and plan.ignored_sections == [] and plan.highest_safety is None
    assert plan.to_dict()["requires_confirmation"] is False


# -- destructive gate -------------------------------------------------------------------------
def test_destructive_refused_without_flag_and_allowed_with_it() -> None:
    plan = plan_migration(base(), mutate([f for f in BASE_FIELDS if f["name"] != "note"]))
    assert plan.requires_confirmation
    assert plan.apply_allowed(False) is False
    assert plan.apply_allowed(allow_destructive=True) is True
    assert [s.kind for s in plan.blocked_steps()] == [StepKind.drop_column]
    assert plan.blocked_steps(True) == []


def test_backfill_plan_is_applicable_without_flag_and_carries_strategy() -> None:
    plan = plan_migration(base(), base([fld("extra", required=True)]))
    assert plan.apply_allowed(False) and not plan.requires_confirmation
    step = plan.steps[0]
    assert step.safety == Safety.backfill and step.backfill_strategy and step.suggested_action
    assert "NOT NULL" in (step.sql_hint or "")


# -- renames ----------------------------------------------------------------------------------
def renamed_field(new_name: str = "title") -> dict[str, Any]:
    fields = copy.deepcopy(BASE_FIELDS)
    fields[2]["name"] = new_name  # note (text) -> title (text), same position
    return mutate(fields)


def test_undeclared_field_rename_is_flagged_destructive_never_guessed() -> None:
    plan = plan_migration(base(), renamed_field())
    assert sorted(kinds(plan)) == sorted([("drop_column", "note", "destructive"), ("add_column", "title", "safe")])
    drop = next(s for s in plan.steps if s.kind == StepKind.drop_column)
    assert drop.suggested_action and drop.suggested_action.startswith("declare a rename")
    assert plan.requires_confirmation


def test_declared_field_rename_is_safe() -> None:
    plan = plan_migration(base(), renamed_field(), renames=[{"entity": "Item", "from": "note", "to": "title"}])
    assert kinds(plan) == [("rename_column", "title", "safe")]
    assert "RENAME COLUMN" in (plan.steps[0].sql_hint or "")
    assert not plan.requires_confirmation


def test_declared_rename_combined_with_type_widening() -> None:
    new = renamed_field()
    new["entities"][0]["fields"][2]["type"] = "text"
    new["entities"][0]["fields"][1]["name"] = "count"
    plan = plan_migration(base(), new, renames=[{"entity": "Item", "from": "qty", "to": "count"}])
    assert kinds(plan)[0] == ("rename_column", "count", "safe")
    assert all(s.safety != Safety.destructive or s.field == "note" for s in plan.steps)


def test_entity_rename_declared_vs_undeclared() -> None:
    old = spec([ent("Item", BASE_FIELDS, table="items")])
    new = spec([ent("Thing", BASE_FIELDS, table="things")])
    undeclared = plan_migration(old, new)
    assert sorted(kinds(undeclared)) == [("create_table", None, "safe"), ("drop_table", None, "destructive")]
    drop = next(s for s in undeclared.steps if s.kind == StepKind.drop_table)
    assert drop.suggested_action and "declare a rename" in drop.suggested_action
    declared = plan_migration(old, new, renames=[{"kind": "entity", "from": "Item", "to": "Thing"}])
    assert kinds(declared) == [("rename_table", None, "safe")]
    assert declared.steps[0].table == "things"


def test_entity_rename_keeping_table_name_is_no_op() -> None:
    old = spec([ent("Item", BASE_FIELDS, table="items")])
    new = spec([ent("Thing", BASE_FIELDS, table="items")])
    assert plan_migration(old, new, renames=[{"from": "Item", "to": "Thing"}]).steps == []


def test_table_name_change_without_rename_is_drop_plus_create() -> None:
    old = spec([ent("Item", BASE_FIELDS, table="items")])
    new = spec([ent("Item", BASE_FIELDS, table="goods")])
    assert sorted(kinds(plan_migration(old, new))) == [("create_table", None, "safe"), ("drop_table", None, "destructive")]


@pytest.mark.parametrize(
    "hint",
    [
        {"entity": "Item", "from": "ghost", "to": "title"},
        {"entity": "Item", "from": "note", "to": "name"},
        {"entity": "Item", "from": "note", "to": "nothere"},
        {"entity": "Nope", "from": "note", "to": "title"},
        {"from": "Item", "to": "Part"},
        {"from": "Ghost", "to": "Part"},
        {"entity": "Item", "from": "note", "to": "note"},
        {"entity": "Item", "from": "note"},
        {"entity": "Item", "from": "note", "to": "title", "extra": 1},
        "Item.note->title",
    ],
)
def test_bad_rename_hints_fail_closed(hint: Any) -> None:
    with pytest.raises(MigrationPlanError):
        plan_migration(base(), renamed_field(), renames=[hint])


def test_duplicate_rename_hint_rejected() -> None:
    h = {"entity": "Item", "from": "note", "to": "title"}
    with pytest.raises(MigrationPlanError, match="duplicate"):
        plan_migration(base(), renamed_field(), renames=[h, dict(h)])


# -- malformed input --------------------------------------------------------------------------
def dup_entity() -> dict[str, Any]:
    s = base()
    s["entities"].append(copy.deepcopy(s["entities"][0]))
    return s


def dup_field() -> dict[str, Any]:
    return mutate([fld("a"), fld("a")])


def dup_table() -> dict[str, Any]:
    return spec([ent("A", [fld("x")], table="same"), ent("B", [fld("x")], table="same")])


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"project": {"name": "x"}},
        {"project": {"name": "x", "slug": "x"}, "entities": "nope"},
        None,
        42,
        "spec",
        mutate([fld("a", "nonsense")]),
        mutate([fld("a", "enum")]),
        dup_entity(),
        dup_field(),
        dup_table(),
        spec([ent("A", [fld("x")])], [rel(frm="A", to="Ghost")]),
    ],
)
def test_malformed_specs_raise_clear_error_on_either_side(bad: Any) -> None:
    with pytest.raises(MigrationPlanError):
        plan_migration(bad, base())
    with pytest.raises(MigrationPlanError):
        plan_migration(base(), bad)


def test_error_names_the_side_and_location() -> None:
    with pytest.raises(MigrationPlanError, match=r"new spec is malformed at \['project'\]"):
        plan_migration(base(), {})


def test_inputs_are_not_mutated() -> None:
    old, new = base(), base([fld("extra", required=True)])
    snap = copy.deepcopy((old, new))
    plan_migration(old, new)
    assert (old, new) == snap


def test_render_outputs() -> None:
    plan = plan_migration(base(), mutate([f for f in BASE_FIELDS if f["name"] != "note"] + [fld("extra", required=True)]))
    text = render_text(plan)
    assert "CONFIRMATION REQUIRED" in text and "[NEEDS BACKFILL]" in text and "[DESTRUCTIVE]" in text
    assert render_json(plan) == plan.to_json()
