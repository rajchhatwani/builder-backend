"""Validation of the `authorization` block: every way to get a policy wrong has a clear error."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def codes(raw: dict[str, Any]) -> list[str]:
    return [i.code for i in validate(Spec.model_validate(raw))]


def with_policy(name: str, policy: dict[str, Any], **extra: Any) -> dict[str, Any]:
    raw = copy.deepcopy(load(name))
    raw["authorization"]["policies"].append(policy)
    for key, value in extra.items():
        raw["authorization"][key] = value
    return raw


def allow_when(when: Any, actions: list[str] | None = None, pid: str = "extra") -> dict[str, Any]:
    return {"id": pid, "effect": "allow", "actions": actions or ["Ticket.list"], "when": when}


def leaf(left: dict, op: str, right: dict | None = None) -> dict:
    return {"left": left, "op": op, **({"right": right} if right is not None else {})}


def test_fixtures_are_valid() -> None:
    assert codes(load("authz_abac")) == []
    assert codes(load("authz_pbac")) == []


def test_rbac_default_is_untouched() -> None:
    raw = load("notes_auth")
    assert codes(raw) == []
    raw["authorization"] = {"model": "rbac"}
    assert codes(raw) == []
    raw["authorization"] = {
        "model": "rbac",
        "policies": [{"id": "p", "effect": "allow", "actions": ["*"]}],
    }
    assert "authz.unused_policies" in codes(raw)


def test_unknown_model() -> None:
    raw = load("authz_abac")
    raw["authorization"]["model"] = "xacml"
    assert codes(raw) == ["invalid_value"]


def test_needs_sign_in_and_no_role_permissions() -> None:
    raw = load("authz_abac")
    raw["auth"]["enabled"] = False
    assert "authz.needs_auth" in codes(raw)
    raw = load("authz_abac")
    raw["auth"]["permissions"] = [{"entity": "Ticket", "operation": "list", "roles": ["admin"]}]
    assert "authz.mixed_models" in codes(raw)
    raw = load("authz_abac")
    del raw["auth"]
    assert "authz.needs_auth" in codes(raw)


def test_no_policies_is_an_error_because_everything_would_be_denied() -> None:
    raw = load("authz_abac")
    raw["authorization"]["policies"] = []
    assert "authz.no_policies" in codes(raw)


@pytest.mark.parametrize(
    ("policy", "code"),
    [
        ({"id": "Bad Id", "effect": "allow", "actions": ["Ticket.list"]}, "invalid_value"),
        (
            {
                "id": "see_own_department",
                "effect": "allow",
                "actions": ["Ticket.list"],
                "when": leaf({"subject": "id"}, "not_null"),
            },
            "duplicate",
        ),
        ({"id": "x", "effect": "maybe", "actions": ["Ticket.list"]}, "invalid_value"),
        ({"id": "x", "effect": "allow", "actions": []}, "authz.no_actions"),
        (
            {
                "id": "x",
                "effect": "allow",
                "actions": ["Ghost.list"],
                "when": leaf({"subject": "id"}, "not_null"),
            },
            "authz.unknown_action",
        ),
        (
            {
                "id": "x",
                "effect": "allow",
                "actions": ["Ticket.explode"],
                "when": leaf({"subject": "id"}, "not_null"),
            },
            "authz.unknown_action",
        ),
        (
            {
                "id": "x",
                "effect": "allow",
                "actions": ["list"],
                "when": leaf({"subject": "id"}, "not_null"),
            },
            "authz.unknown_action",
        ),
        ({"id": "x", "effect": "allow", "actions": ["Ticket.delete"]}, "authz.open_write"),
        ({"id": "x", "effect": "allow", "actions": ["*"]}, "authz.open_write"),
        ({"id": "x", "effect": "deny", "actions": ["*"]}, "authz.deny_all"),
    ],
)
def test_policy_level_errors_under_abac(policy: dict[str, Any], code: str) -> None:
    assert code in codes(with_policy("authz_abac", policy))


def test_an_unconditional_read_is_allowed_but_not_an_unconditional_write() -> None:
    assert (
        codes(
            with_policy(
                "authz_abac",
                {"id": "everyone_reads", "effect": "allow", "actions": ["Ticket.list"]},
            )
        )
        == []
    )
    assert "authz.open_write" in codes(
        with_policy(
            "authz_abac", {"id": "everyone_writes", "effect": "allow", "actions": ["Ticket.update"]}
        )
    )


@pytest.mark.parametrize(
    ("when", "code"),
    [
        ({"all": []}, "authz.bad_condition"),
        ({"not": leaf({"subject": "id"}, "not_null")}, "authz.bad_condition"),
        (leaf({"subject": "id"}, "eval", {"literal": 1}), "authz.bad_condition"),
        (leaf({"python": "x"}, "eq", {"literal": 1}), "authz.bad_condition"),
        (
            leaf({"subject": "password_hash"}, "eq", {"literal": "x"}),
            "authz.unknown_subject_attribute",
        ),
        (leaf({"env": "os_environ"}, "eq", {"literal": "x"}), "authz.unknown_env_attribute"),
        (leaf({"resource": "salary"}, "eq", {"literal": 1}), "authz.unknown_resource_attribute"),
        (leaf({"resource": "priority"}, "eq", {"literal": "high"}), "authz.type_mismatch"),
        (leaf({"resource": "status"}, "eq", {"literal": "archived"}), "authz.bad_enum_value"),
        (leaf({"resource": "priority"}, "gt", {"literal": True}), "authz.bad_operand"),
        (leaf({"resource": "created_by_id"}, "lt", {"subject": "id"}), "authz.bad_operand"),
        (
            leaf({"resource": "created_by_id"}, "eq", {"literal": "not-a-uuid"}),
            "authz.type_mismatch",
        ),
        (leaf({"resource": "department"}, "eq", {"subject": "roles"}), "authz.bad_operand"),
        (leaf({"resource": "department"}, "in", {"literal": "a"}), "authz.bad_operand"),
        (leaf({"resource": "department"}, "in", {"literal": []}), "authz.bad_literal"),
        (leaf({"resource": "department"}, "in", {"literal": ["a", 1]}), "authz.bad_literal"),
        (leaf({"resource": "priority"}, "in", {"literal": ["a", "b"]}), "authz.type_mismatch"),
        (leaf({"literal": "a"}, "in", {"resource": "department"}), "authz.in_needs_list"),
        (leaf({"resource": "department"}, "eq", {"literal": {"x": 1}}), "authz.bad_literal"),
        (leaf({"resource": "department"}, "is_null", {"literal": 1}), "authz.bad_condition"),
        (leaf({"env": "client_ip"}, "ip_in", {"literal": ["10.0.0.0/33"]}), "authz.bad_network"),
        (leaf({"env": "client_ip"}, "ip_in", {"literal": "10.0.0.0/8"}), "authz.bad_operand"),
        (
            leaf({"resource": "department"}, "ip_in", {"literal": ["10.0.0.0/8"]}),
            "authz.bad_operand",
        ),
        (leaf({"subject": "roles"}, "eq", {"literal": "admin"}), "authz.bad_operand"),
    ],
)
def test_condition_errors(when: Any, code: str) -> None:
    assert code in codes(with_policy("authz_abac", allow_when(when)))


@pytest.mark.parametrize(
    "when",
    [
        leaf({"resource": "priority"}, "gte", {"literal": 2.5}),
        leaf(
            {"resource": "created_by_id"}, "eq", {"literal": "00000000-0000-0000-0000-00000000000a"}
        ),
        leaf({"resource": "created_at"}, "gt", {"literal": "2026-01-01T00:00:00"}),
        leaf({"resource": "department"}, "in", {"subject": "roles"}),
        leaf({"resource": "status"}, "not_in", {"literal": ["closed"]}),
        leaf({"resource": "id"}, "not_null"),
        leaf({"subject": "department"}, "eq", {"literal": "sales"}),
        leaf({"env": "hour_utc"}, "lt", {"literal": 18}),
        leaf({"env": "client_ip"}, "ip_in", {"literal": ["10.0.0.0/8", "fd00::/8"]}),
        leaf({"subject": "roles"}, "contains", {"literal": "admin"}),
        {
            "any": [
                {
                    "all": [
                        leaf({"resource": "priority"}, "lt", {"literal": 3}),
                        leaf({"env": "weekday_utc"}, "lt", {"literal": 5}),
                    ]
                },
                leaf({"subject": "id"}, "eq", {"resource": "created_by_id"}),
            ]
        },
    ],
)
def test_valid_conditions(when: Any) -> None:
    assert codes(with_policy("authz_abac", allow_when(when))) == []


def test_an_expression_string_is_not_even_a_valid_spec() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Spec.model_validate(with_policy("authz_abac", allow_when("status == 'open'")))


def test_size_limits() -> None:
    wide = {"all": [leaf({"resource": "priority"}, "eq", {"literal": i}) for i in range(30)]}
    assert "authz.condition_too_large" in codes(with_policy("authz_abac", allow_when(wide)))
    deep: Any = leaf({"resource": "priority"}, "eq", {"literal": 1})
    for _ in range(5):
        deep = {"all": [deep]}
    assert "authz.condition_too_large" in codes(with_policy("authz_abac", allow_when(deep)))


def test_wildcard_policy_may_only_use_attributes_every_entity_has() -> None:
    raw = with_policy(
        "authz_pbac",
        {
            "id": "any_status",
            "effect": "allow",
            "actions": ["*"],
            "when": leaf({"resource": "status"}, "eq", {"literal": "published"}),
        },
        attachments={
            "*": ["read_published", "comment", "archived_is_frozen", "any_status"],
            "editor": ["author"],
            "manager": ["manage"],
        },
    )
    assert "authz.unknown_resource_attribute" in codes(raw)  # Comment has no status


def test_unknown_action_operation_for_entity_that_disabled_it() -> None:
    raw = load("authz_abac")
    raw["entities"][0]["options"]["operations"] = ["list", "get", "create"]
    found = codes(raw)
    assert (
        found.count("authz.unknown_action") >= 2
    )  # update / replace / delete policies now name missing operations


# -- attachments (pbac) -------------------------------------------------------------------


def test_abac_has_no_attachments() -> None:
    raw = load("authz_abac")
    raw["authorization"]["attachments"] = {"*": ["see_own_department"]}
    assert "authz.attachments_not_used" in codes(raw)


@pytest.mark.parametrize(
    ("attachments", "code"),
    [
        (
            {
                "*": ["read_published", "comment", "archived_is_frozen"],
                "editor": ["author", "ghost"],
                "manager": ["manage"],
            },
            "authz.unknown_policy",
        ),
        (
            {
                "*": ["read_published", "comment", "archived_is_frozen"],
                "wizard": ["author"],
                "manager": ["manage"],
            },
            "authz.unknown_role",
        ),
        (
            {"*": ["read_published", "comment", "archived_is_frozen"], "editor": ["author"]},
            "authz.unattached_policy",
        ),
        (
            {
                "*": ["read_published", "comment", "archived_is_frozen"],
                "public": ["author"],
                "editor": ["author"],
                "manager": ["manage"],
            },
            "authz.public_not_supported",
        ),
    ],
)
def test_attachment_errors(attachments: dict[str, list[str]], code: str) -> None:
    raw = load("authz_pbac")
    raw["authorization"]["attachments"] = attachments
    assert code in codes(raw)


def test_pbac_allows_unconditional_role_grants() -> None:
    # `manage` is unconditional and carried by `manager`: that is role-based, not "everyone".
    assert codes(load("authz_pbac")) == []
