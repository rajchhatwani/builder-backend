# ruff: noqa: E501
"""Audit B1-006: m2m join tables follow a declared table rename and a swapped table."""

from typing import Any

from app.services.migration_planner import StepKind, plan_migration


def _ent(name: str, table: str) -> dict[str, Any]:
    return {"name": name, "table_name": table, "plural_path": table, "options": {}, "fields": [{"name": "code", "type": "string"}]}


def _spec(entities: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"spec_version": 1, "project": {"name": "T", "slug": "t"}, "entities": entities, "relations": relations}


def _m2m(frm: str) -> dict[str, Any]:
    return {"kind": "many_to_many", "from_entity": frm, "to_entity": "Tag", "from_name": "tags", "to_name": "orders"}


TAG = _ent("Tag", "tags")


def test_declared_rename_renames_join_table() -> None:
    old = _spec([_ent("Order", "orders"), TAG], [_m2m("Order")])
    new = _spec([_ent("Purchase", "purchases"), TAG], [_m2m("Purchase")])
    plan = plan_migration(old, new, [{"kind": "entity", "from": "Order", "to": "Purchase"}])
    renames = [(s.table, s.sql_hint) for s in plan.steps if s.kind == StepKind.rename_table]
    assert ("purchases_tags", 'ALTER TABLE "orders_tags" RENAME TO "purchases_tags"') in renames
    assert not [s for s in plan.steps if s.kind in (StepKind.drop_table, StepKind.create_table)]


def test_undeclared_table_swap_recreates_join_table() -> None:
    old = _spec([_ent("Order", "orders"), TAG], [_m2m("Order")])
    new = _spec([_ent("Order", "orders2"), TAG], [_m2m("Order")])
    plan = plan_migration(old, new)
    drops = {s.table for s in plan.steps if s.kind == StepKind.drop_table}
    creates = {s.table for s in plan.steps if s.kind == StepKind.create_table}
    assert "orders_tags" in drops and "orders2_tags" in creates


def test_swapped_target_table_keeps_join_table_untouched() -> None:
    old = _spec([_ent("Order", "orders"), TAG], [_m2m("Order")])
    new = _spec([_ent("Order", "orders"), _ent("Tag", "tags2")], [_m2m("Order")])
    plan = plan_migration(old, new)
    assert not [s for s in plan.steps if s.table == "orders_tags"]
