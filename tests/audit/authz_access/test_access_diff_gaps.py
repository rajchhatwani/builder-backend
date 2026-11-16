"""Hostile tests for `access_diff` / `weakens`: edits that give someone more access must be flagged.
Pure functions over Spec; no database."""

import copy
from typing import Any

from app.core.access_layers import access_diff, weakens
from app.core.spec_models import Spec
from app.core.validation import validate
from tests.unit.test_access_layers import base


def _spec(raw: dict[str, Any]) -> Spec:
    s = Spec.model_validate(raw)
    assert [i.code for i in validate(s)] == [], "the attack spec must itself be valid"
    return s


def _perm(raw: dict[str, Any], op: str) -> dict[str, Any]:
    return next(p for p in raw["auth"]["permissions"] if p["operation"] == op)


def test_new_self_assignable_role_with_full_access_is_a_weakening() -> None:
    before = base()
    after = copy.deepcopy(before)
    after["auth"]["roles"].append({"name": "root", "label": "Root", "self_assignable": True})
    for p in after["auth"]["permissions"]:
        p["roles"].append("root")
    after["authorization"]["field_access"][0]["read_roles"].append("root")
    after["authorization"]["field_access"][0]["write_roles"].append("root")
    diff = access_diff(_spec(before), _spec(after))
    # anyone can claim a self-assignable role at sign-up, so a powerful one is a gain for everybody
    assert diff["weakens"] is True, diff["counts"]


def test_new_default_role_with_access_is_a_weakening() -> None:
    before = base()
    after = copy.deepcopy(before)
    after["auth"]["roles"].append({"name": "guest", "label": "Guest", "is_default": True})
    _perm(after, "delete")["roles"].append("guest")
    diff = access_diff(_spec(before), _spec(after))
    assert diff["weakens"] is True, diff["counts"]


def test_enabling_a_new_operation_on_an_existing_entity_is_a_weakening() -> None:
    before = base()
    before["entities"][0]["options"] = {"operations": ["list", "get"]}
    after = copy.deepcopy(before)
    after["entities"][0]["options"] = {"operations": ["list", "get", "delete"]}
    _perm(after, "delete")["roles"] = ["admin", "hr", "staff"]
    diff = access_diff(_spec(before), _spec(after))
    assert diff["weakens"] is True, [c for c in diff["changes"] if c["target"] == "delete"][:3]


def test_enabling_an_operation_with_no_permission_slot_is_public_and_flagged() -> None:
    before = base()
    before["entities"][0]["options"] = {"operations": ["list", "get"]}
    after = copy.deepcopy(before)
    after["entities"][0]["options"] = {"operations": ["list", "get", "delete"]}
    after["auth"]["permissions"] = [p for p in after["auth"]["permissions"] if p["operation"] != "delete"]
    diff = access_diff(_spec(before), _spec(after))
    assert diff["weakens"] is True


def test_adding_a_parent_via_inherits_from_is_a_gain() -> None:
    before = base()
    after = copy.deepcopy(before)
    for r in after["auth"]["roles"]:
        if r["name"] == "staff":
            r["inherits_from"] = "admin"
    diff = access_diff(_spec(before), _spec(after))
    assert diff["weakens"] is True
    assert "staff" in diff["roles_gaining"]


def test_emptying_a_permission_role_list_makes_it_public_and_is_a_gain() -> None:
    before = base()
    after = copy.deepcopy(before)
    _perm(after, "delete")["roles"] = []
    diff = access_diff(_spec(before), _spec(after))
    assert diff["weakens"] is True
    assert "(public)" in diff["roles_gaining"] or "staff" in diff["roles_gaining"]


def test_dropping_the_field_rule_is_a_gain_for_each_role_that_now_reads_it() -> None:
    before = base()
    after = copy.deepcopy(before)
    after["authorization"]["field_access"] = []
    diff = access_diff(_spec(before), _spec(after))
    assert diff["weakens"] is True
    assert "field:Person.salary.read" in diff["roles_gaining"]["staff"]


def test_widening_write_roles_only_is_a_gain() -> None:
    before = base()
    after = copy.deepcopy(before)
    after["authorization"]["field_access"][0]["write_roles"] = ["hr", "admin"]
    d = access_diff(_spec(before), _spec(after))
    assert d["weakens"] is True and d["roles_gaining"] == {"admin": ["field:Person.salary.write"]}


def test_row_scope_widening_is_a_gain_for_each_step() -> None:
    steps = [("owner", None), ("role_scoped", None), (None, None)]
    for i in range(len(steps) - 1):
        before, after = base(), base()
        _perm(before, "list").pop("row_rule", None)
        _perm(after, "list").pop("row_rule", None)
        if steps[i][0]:
            _perm(before, "list")["row_rule"] = steps[i][0]
        if steps[i + 1][0]:
            _perm(after, "list")["row_rule"] = steps[i + 1][0]
        assert weakens(_spec(before), _spec(after)), (steps[i], steps[i + 1])
        assert not weakens(_spec(after), _spec(before)), "tightening must not be flagged"


def test_custom_filter_value_edit_is_a_gain() -> None:
    before = base()
    _perm(before, "list").update(row_rule="custom_filter", custom_filter_field="name", custom_filter_value="a")
    after = copy.deepcopy(before)
    _perm(after, "list")["custom_filter_value"] = "b"
    assert weakens(_spec(before), _spec(after)), "an opaque filter edit may reach other rows"


def test_rename_cannot_launder_a_permission_widening() -> None:
    before = base()
    after = copy.deepcopy(before)
    after["entities"][0]["name"] = "Human"
    after["entities"][0]["table_name"] = "humans"
    after["entities"][0]["plural_path"] = "humans"
    for p in after["auth"]["permissions"]:
        p["entity"] = "Human"
    for f in after["authorization"]["field_access"]:
        f["entity"] = "Human"
    _perm(after, "delete")["roles"] = ["admin", "hr", "staff"]
    diff = access_diff(_spec(before), _spec(after))
    assert diff["weakens"] is True, diff["counts"]


def test_role_rename_cannot_launder_a_gain() -> None:
    before = base()
    after = copy.deepcopy(before)
    for r in after["auth"]["roles"]:
        if r["name"] == "hr":
            r["name"] = "people"
    for p in after["auth"]["permissions"]:
        p["roles"] = ["people" if x == "hr" else x for x in p["roles"]]
    for f in after["authorization"]["field_access"]:
        f["read_roles"] = ["people" if x == "hr" else x for x in f["read_roles"]]
        f["write_roles"] = ["people" if x == "hr" else x for x in f["write_roles"]]
    _perm(after, "delete")["roles"] = ["admin", "people"]
    diff = access_diff(_spec(before), _spec(after))
    assert diff["weakens"] is True
    assert "people" in diff["roles_gaining"]


def test_turning_sign_in_off_is_a_gain_for_the_public() -> None:
    before = base()
    after = copy.deepcopy(before)
    after["auth"]["enabled"] = False
    after.pop("authorization")  # field rules need sign-in; without them the spec is valid
    diff = access_diff(_spec(before), _spec(after))
    assert diff["weakens"] is True


def test_diff_is_deterministic_and_order_independent() -> None:
    before = base()
    after = copy.deepcopy(before)
    _perm(after, "delete")["roles"] = ["staff", "hr", "admin"]
    after["auth"]["permissions"].reverse()
    a = access_diff(_spec(before), _spec(after))
    b = access_diff(_spec(before), _spec(after))
    assert a == b
    c = copy.deepcopy(after)
    _perm(c, "delete")["roles"] = ["admin", "hr", "staff"]
    assert access_diff(_spec(before), _spec(c))["changes"] == a["changes"]


def test_identical_specs_are_not_a_weakening() -> None:
    assert access_diff(_spec(base()), _spec(base()))["weakens"] is False
