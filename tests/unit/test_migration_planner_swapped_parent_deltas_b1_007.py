# ruff: noqa: E501
"""Audit B1-007: swapped parent + kept child still plans required/kind deltas of the relation."""

from typing import Any

from app.services.migration_planner import plan_migration


def _ent(name: str, table: str) -> dict[str, Any]:
    return {"name": name, "table_name": table, "plural_path": table, "options": {}, "fields": [{"name": "code", "type": "string"}]}


def _spec(entities: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"spec_version": 1, "project": {"name": "T", "slug": "t"}, "entities": entities, "relations": relations}


def _o2m(**kw: Any) -> dict[str, Any]:
    return {"kind": "one_to_many", "from_entity": "Order", "to_entity": "Item", "from_name": "items", "to_name": "order", **kw}


ITEM = _ent("Item", "items")


def _kinds(old_rel: dict[str, Any], new_rel: dict[str, Any]) -> list[tuple[str, str]]:
    old = _spec([_ent("Order", "orders"), ITEM], [old_rel])
    new = _spec([_ent("Order", "orders2"), ITEM], [new_rel])
    return sorted((s.kind.value, s.table) for s in plan_migration(old, new).steps)


def test_swapped_parent_required_delta_planned() -> None:
    kinds = _kinds(_o2m(), _o2m(required=True))
    assert ("add_fk", "items") in kinds
    assert ("set_not_null", "items") in kinds


def test_swapped_parent_relax_required_planned() -> None:
    assert ("relax_not_null", "items") in _kinds(_o2m(required=True), _o2m())


def test_swapped_parent_kind_unique_delta_planned() -> None:
    kinds = _kinds(_o2m(), _o2m(kind="one_to_one"))
    assert ("add_unique", "items") in kinds
    back = _kinds(_o2m(kind="one_to_one"), _o2m())
    assert ("drop_unique", "items") in back


def test_swapped_parent_on_delete_only_add_fk() -> None:
    kinds = _kinds(_o2m(), _o2m(on_delete="cascade"))
    assert ("add_fk", "items") in kinds
    assert ("alter_fk", "items") not in kinds
