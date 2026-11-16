# ruff: noqa: E501
"""Audit B1-024: planner join-table naming, relation removal, string-length type changes."""

from typing import Any

from app.core import naming
from app.services.migration_planner import StepKind, plan_migration


def _fld(name: str, type_: str = "string", **kw: Any) -> dict[str, Any]:
    return {"name": name, "type": type_, **kw}


def _ent(name: str, table: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "table_name": table, "plural_path": table, "options": {}, "fields": fields}


def _spec(entities: list[dict[str, Any]], relations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"spec_version": 1, "project": {"name": "T", "slug": "t"}, "entities": entities, "relations": relations or []}


M2M = {"kind": "many_to_many", "from_entity": "Order", "to_entity": "Tag", "from_name": "tags", "to_name": "orders"}
O2M = {"kind": "one_to_many", "from_entity": "Customer", "to_entity": "Order", "from_name": "orders", "to_name": "customer"}


def _order(extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return _ent("Order", "orders", [_fld("code", "uuid")] + (extra or []))


def test_m2m_join_table_uses_table_name_like_generator() -> None:
    tag = _ent("Tag", "tags", [_fld("label")])
    old = _spec([_order(), tag], [M2M])
    new = _spec([_order(), tag])
    plan = plan_migration(old, new)
    step = next(s for s in plan.steps if s.kind == StepKind.drop_table)
    expected = naming.join_table_name("orders", "tags")
    assert step.table == expected == "orders_tags"
    assert f'DROP TABLE "{expected}"' in (step.sql_hint or "")
    add = plan_migration(new, old)
    cstep = next(s for s in add.steps if s.kind == StepKind.create_table)
    assert cstep.table == expected


def test_removing_m2m_target_entity_still_drops_join_table() -> None:
    tag = _ent("Tag", "tags", [_fld("label")])
    old = _spec([_order(), tag], [M2M])
    new = _spec([_order()])
    plan = plan_migration(old, new)
    tables = {s.table for s in plan.steps if s.kind == StepKind.drop_table}
    assert "orders_tags" in tables


def test_removing_fk_parent_drops_child_fk_column() -> None:
    cust = _ent("Customer", "customers", [_fld("name")])
    old = _spec([cust, _order()], [O2M])
    new = _spec([_order()])
    plan = plan_migration(old, new)
    got = {(s.kind, s.table, s.field) for s in plan.steps}
    assert (StepKind.drop_column, "orders", "customer_id") in got
    assert (StepKind.drop_fk, "orders", "customer_id") in got


def test_removing_fk_child_does_not_plan_column_drop() -> None:
    cust = _ent("Customer", "customers", [_fld("name")])
    old = _spec([cust, _order()], [O2M])
    new = _spec([cust])
    plan = plan_migration(old, new)
    assert not [s for s in plan.steps if s.kind == StepKind.drop_column]


def _plan_code(old_t: str, new_f: dict[str, Any], old_f: dict[str, Any] | None = None) -> Any:
    old = _spec([_ent("Order", "orders", [old_f or _fld("code", old_t)])])
    new = _spec([_ent("Order", "orders", [new_f])])
    return plan_migration(old, new)


def test_uuid_to_short_string_is_destructive() -> None:
    plan = _plan_code("uuid", _fld("code", "string", max_length=10))
    assert [s.safety.value for s in plan.steps] == ["destructive"]
    assert not plan.apply_allowed()


def test_type_to_string_that_fits_or_unbounded_stays_safe() -> None:
    assert _plan_code("uuid", _fld("code", "string", max_length=36)).apply_allowed()
    assert _plan_code("uuid", _fld("code", "string")).apply_allowed()
    assert _plan_code("integer", _fld("code", "string", max_length=11)).apply_allowed()


def test_enum_to_string_checks_longest_value() -> None:
    old = _fld("code", "enum", enum_values=["abc", "abcdefghij"])
    assert not _plan_code("enum", _fld("code", "string", max_length=5), old).apply_allowed()
    assert _plan_code("enum", _fld("code", "string", max_length=10), old).apply_allowed()
