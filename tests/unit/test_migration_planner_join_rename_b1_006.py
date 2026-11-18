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


def _o2m() -> dict[str, Any]:
    return {"kind": "one_to_many", "from_entity": "Order", "to_entity": "Item", "from_name": "items", "to_name": "order"}


def _m2m_item() -> dict[str, Any]:
    return {"kind": "many_to_many", "from_entity": "Order", "to_entity": "Item", "from_name": "items", "to_name": "order"}


ITEM = _ent("Item", "items")


def _kinds(plan: Any) -> list[tuple[str, str]]:
    return sorted((s.kind.value, s.table) for s in plan.steps)


def test_swapped_parent_replans_fk_on_kept_child() -> None:
    old = _spec([_ent("Order", "orders"), ITEM], [_o2m()])
    new = _spec([_ent("Order", "orders2"), ITEM], [_o2m()])
    kinds = _kinds(plan_migration(old, new))
    assert ("add_fk", "items") in kinds
    assert ("add_column", "items") not in kinds


def test_swapped_parent_with_removed_relation_drops_child_column_only() -> None:
    old = _spec([_ent("Order", "orders"), ITEM], [_o2m()])
    new = _spec([_ent("Order", "orders2"), ITEM], [])
    kinds = _kinds(plan_migration(old, new))
    assert ("drop_column", "items") in kinds
    assert ("drop_fk", "items") not in kinds


def test_m2m_to_o2m_flip_with_swapped_parent_adds_fk_column() -> None:
    old = _spec([_ent("Order", "orders"), ITEM], [_m2m_item()])
    new = _spec([_ent("Order", "orders2"), ITEM], [_o2m()])
    kinds = _kinds(plan_migration(old, new))
    assert ("add_column", "items") in kinds and ("add_fk", "items") in kinds
    assert ("drop_table", "orders_items") in kinds


def test_o2m_to_m2m_flip_with_swapped_parent_drops_child_column() -> None:
    old = _spec([_ent("Order", "orders"), ITEM], [_o2m()])
    new = _spec([_ent("Order", "orders2"), ITEM], [_m2m_item()])
    kinds = _kinds(plan_migration(old, new))
    assert ("drop_column", "items") in kinds and ("create_table", "orders2_items") in kinds


def test_m2m_added_and_removed_while_from_swapped() -> None:
    added = _kinds(plan_migration(_spec([_ent("Order", "orders"), TAG], []), _spec([_ent("Order", "orders2"), TAG], [_m2m("Order")])))
    assert ("create_table", "orders2_tags") in added
    removed = _kinds(plan_migration(_spec([_ent("Order", "orders"), TAG], [_m2m("Order")]), _spec([_ent("Order", "orders2"), TAG], [])))
    assert ("drop_table", "orders_tags") in removed


def test_declared_rename_with_unchanged_table_makes_no_join_rename() -> None:
    old = _spec([_ent("Order", "orders"), TAG], [_m2m("Order")])
    new = _spec([_ent("Purchase", "orders"), TAG], [_m2m("Purchase")])
    plan = plan_migration(old, new, [{"kind": "entity", "from": "Order", "to": "Purchase"}])
    assert not [s for s in plan.steps if s.table == "orders_tags"]
