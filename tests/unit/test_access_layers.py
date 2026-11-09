"""B4-7 access layers (object / field / row), access-diff; B4-3 search permission filter."""

import copy
from typing import Any

import pytest

from app.core.access_layers import access_diff, access_matrix, readable_fields, weakens
from app.core.search import FtsAdapter, OpenSearchAdapter, row_scope, search
from app.core.spec_models import Spec
from app.core.validation import validate

ROLES = [
    {"name": "admin", "label": "Admin"},
    {"name": "hr", "label": "HR"},
    {"name": "staff", "label": "Staff", "is_default": True},
]


def base() -> dict[str, Any]:
    return {
        "spec_version": 1,
        "project": {"name": "People", "slug": "people", "description": None, "db_engine": "postgres"},
        "entities": [
            {
                "name": "Person",
                "table_name": "people",
                "plural_path": "people",
                "options": {},
                "fields": [
                    {"name": "name", "type": "string", "max_length": 80},
                    {"name": "notes", "type": "text"},
                    {"name": "salary", "type": "string", "max_length": 20},
                ],
            }
        ],
        "relations": [],
        "auth": {
            "enabled": True,
            "password_reset": {"email_magic_link": False, "sms_otp": False},
            "registration": {"email_verification_required": False},
            "roles": copy.deepcopy(ROLES),
            "permissions": [
                {"entity": "Person", "operation": "list", "roles": ["admin", "hr", "staff"], "row_rule": "role_scoped"},
                {"entity": "Person", "operation": "get", "roles": ["admin", "hr", "staff"]},
                {"entity": "Person", "operation": "create", "roles": ["admin", "hr"]},
                {"entity": "Person", "operation": "update", "roles": ["admin", "hr"]},
                {"entity": "Person", "operation": "replace", "roles": ["admin", "hr"]},
                {"entity": "Person", "operation": "delete", "roles": ["admin"]},
                {"entity": "Person", "operation": "head", "roles": ["admin", "hr", "staff"]},
            ],
        },
        "authorization": {
            "model": "rbac",
            "field_access": [
                {"entity": "Person", "field": "salary", "read_roles": ["hr", "admin"], "write_roles": ["hr"]}
            ],
        },
    }


def spec(raw: dict[str, Any] | None = None) -> Spec:
    return Spec.model_validate(raw or base())


def cell(m: dict[str, Any], layer: str, target: str, role: str) -> str | None:
    for c in m["cells"]:
        if (c["layer"], c["target"], c["role"]) == (layer, target, role):
            return str(c["value"])
    return None


def test_fixture_is_valid() -> None:
    assert [i.code for i in validate(spec())] == []


def test_matrix_three_layers() -> None:
    m = access_matrix(spec())
    assert cell(m, "object", "delete", "admin") == "yes"
    assert cell(m, "object", "delete", "staff") == "no"
    assert cell(m, "object", "list", "staff") == "yes"
    assert cell(m, "row", "list", "staff") == "own (admins: all)"
    assert cell(m, "row", "list", "admin") == "all"
    assert cell(m, "field", "salary.read", "staff") == "no"
    assert cell(m, "field", "salary.read", "hr") == "yes"
    assert cell(m, "field", "salary.write", "admin") == "no"  # narrower than the object layer
    assert cell(m, "field", "name.write", "hr") == "yes"
    assert cell(m, "field", "name.write", "staff") == "no"  # object layer forbids create/update


def test_role_inheritance_counts() -> None:
    raw = base()
    raw["auth"]["roles"][1]["inherits_from"] = "staff"  # hr inherits staff
    raw["auth"]["permissions"][0]["roles"] = ["staff"]
    m = access_matrix(spec(raw))
    assert cell(m, "object", "list", "hr") == "yes"
    assert cell(m, "object", "list", "admin") == "no"


def test_diff_object_field_row_exact_roles() -> None:
    before = spec()
    raw = copy.deepcopy(base())
    # object: staff may now create; field: staff may read salary; row: list no longer owner-scoped
    raw["auth"]["permissions"][2]["roles"] = ["admin", "hr", "staff"]
    raw["authorization"]["field_access"][0]["read_roles"] = ["hr", "admin", "staff"]
    raw["auth"]["permissions"][0]["row_rule"] = None
    d = access_diff(before, spec(raw))
    assert d["weakens"] is True
    # hr is not an admin, so its owner-scoped list becomes "all rows" too
    assert set(d["roles_gaining"]) == {"staff", "hr"}
    assert d["roles_gaining"]["hr"] == ["row:Person.list"]
    assert d["roles_losing"] == {}
    got = {(c["layer"], c["target"], c["role"], c["effect"]) for c in d["changes"]}
    assert ("object", "create", "staff", "gain") in got
    assert ("field", "salary.read", "staff", "gain") in got
    assert ("row", "list", "staff", "gain") in got
    # create now allowed for staff -> name.write etc. follow from the object layer
    assert ("field", "name.write", "staff", "gain") in got
    assert all(c["role"] in ("staff", "hr") for c in d["changes"])


def test_diff_losing_is_not_a_weakening() -> None:
    raw = base()
    raw["auth"]["permissions"][2]["roles"] = ["admin"]
    d = access_diff(spec(), spec(raw))
    assert d["weakens"] is False
    assert set(d["roles_losing"]) == {"hr"}
    assert weakens(spec(), spec(raw)) == []


def test_diff_identical_and_new_entity() -> None:
    assert access_diff(spec(), spec())["changes"] == []
    raw = base()
    raw["entities"].append(
        {"name": "Team", "table_name": "teams", "plural_path": "teams", "options": {}, "fields": [{"name": "title", "type": "string"}]}
    )
    d = access_diff(spec(), spec(raw))
    assert d["weakens"] is False  # a new entity is "added", reviewed through its own permissions
    assert {c["effect"] for c in d["changes"]} == {"added"}


def test_validation_of_field_access() -> None:
    def codes(mutate: Any) -> list[str]:
        raw = base()
        mutate(raw["authorization"]["field_access"])
        return [i.code for i in validate(spec(raw))]

    assert "unknown_field" in codes(lambda f: f[0].update(field="nope"))
    assert "unknown_entity" in codes(lambda f: f[0].update(entity="Nope"))
    assert "unknown_reference" in codes(lambda f: f[0].update(read_roles=["ghost"]))
    assert "duplicate_name" in codes(lambda f: f.append(copy.deepcopy(f[0])))
    assert "required" in codes(lambda f: f[0].update(read_roles=None, write_roles=None))


# -- search ---------------------------------------------------------------------------------

ROWS = [
    {"id": "1", "name": "Ada Lovelace", "notes": "engineer", "salary": "9000", "created_by_id": "u-staff"},
    {"id": "2", "name": "Ada Byron", "notes": "poet", "salary": "5000", "created_by_id": "u-other"},
    {"id": "3", "name": "Grace Hopper", "notes": "admiral ada", "salary": "9000", "created_by_id": "u-other"},
]
STAFF = {"id": "u-staff", "roles": ["staff"]}
HR = {"id": "u-hr", "roles": ["hr"]}
ADMIN = {"id": "u-admin", "roles": ["admin"]}


@pytest.mark.parametrize("adapter", [FtsAdapter(), OpenSearchAdapter()])
def test_search_row_and_field_filter(adapter: Any) -> None:
    s = spec()
    r = search(s, adapter, ROWS, "Person", "ada", STAFF)
    assert [h["id"] for h in r["hits"]] == ["1"]  # staff reaches only own rows
    assert r["total"] == 1
    assert "salary" not in r["hits"][0]
    # admin sees all rows (role_scoped), but admin has no salary write; read yes
    r = search(s, adapter, ROWS, "Person", "ada", ADMIN)
    assert r["total"] == 3
    assert r["hits"][0]["salary"]


@pytest.mark.parametrize("adapter", [FtsAdapter(), OpenSearchAdapter()])
def test_hidden_field_never_matches_or_counts(adapter: Any) -> None:
    s = spec()
    assert search(s, adapter, ROWS, "Person", "9000", STAFF) == {"hits": [], "total": 0}
    assert search(s, adapter, ROWS, "Person", "9000", ADMIN)["total"] == 2


def test_row_hidden_by_rule_not_counted_and_adapter_swap_agrees() -> None:
    s = spec()
    for subject in (STAFF, HR, ADMIN, {"id": "x", "roles": []}, {"roles": ["ghost"]}):
        a = search(s, FtsAdapter(), ROWS, "Person", "ada", subject)
        b = search(s, OpenSearchAdapter(), ROWS, "Person", "ada", subject)
        assert a == b
    assert search(s, FtsAdapter(), ROWS, "Person", "ada", {"roles": ["ghost"]})["total"] == 0


def test_misbehaving_adapter_is_refiltered() -> None:
    class Leaky:
        def search(self, rows: Any, query: Any, fields: Any, scope: Any, subject: Any) -> Any:
            return list(rows)

    r = search(spec(), Leaky(), ROWS, "Person", "x", STAFF)
    assert [h["id"] for h in r["hits"]] == ["1"] and r["total"] == 1


def test_filter_and_tenant_scopes() -> None:
    raw = base()
    raw["auth"]["multi_tenant"] = True
    raw["auth"]["roles"].append({"name": "user", "label": "User"}) if False else None
    raw["auth"]["permissions"][0].update(row_rule="tenant")
    sc = row_scope(spec(raw), "Person", {"id": "u", "roles": ["staff"], "tenant_id": "t1"})
    assert sc.tenant and sc.allows({"tenant_id": "t1"}, {"tenant_id": "t1"})
    assert not sc.allows({"tenant_id": "t2"}, {"tenant_id": "t1"})
    assert not sc.allows({"tenant_id": "t1"}, {})
    sql, _ = sc.sql()
    assert "tenant_id = :caller_tenant" in sql
    raw = base()
    raw["auth"]["permissions"][0].update(row_rule="custom_filter", custom_filter_field="notes", custom_filter_value="poet")
    s = spec(raw)
    r = search(s, FtsAdapter(), ROWS, "Person", "ada", STAFF)
    assert [h["id"] for h in r["hits"]] == ["2"]


def test_readable_fields() -> None:
    assert readable_fields(spec(), "Person", ["staff"]) == {"name", "notes"}
    assert readable_fields(spec(), "Person", ["hr"]) == {"name", "notes", "salary"}
    assert readable_fields(spec(), "Nope", ["hr"]) == set()


def test_auth_disabled_means_everything_public_and_is_a_weakening() -> None:
    raw = base()
    raw["auth"]["enabled"] = False
    d = access_diff(spec(), spec(raw))
    assert d["weakens"] is True
    assert "(public)" in d["roles_gaining"]


def test_non_string_roles_do_not_crash() -> None:
    assert readable_fields(spec(), "Person", [["admin"], 3, "hr"]) == {"name", "notes", "salary"}  # type: ignore[list-item]
