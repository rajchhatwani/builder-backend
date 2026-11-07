"""B3-5 pure parts: risk flags, org policy floor, who must be the owner."""

import copy
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.core.spec_models import Spec
from app.services.agent.approval_service import (
    ApprovalPolicy,
    effective_policy,
    requires_owner,
    risk_flags,
)

BASE: dict[str, Any] = {
    "project": {"name": "Shop", "slug": "shop"},
    "entities": [
        {
            "name": "Item",
            "table_name": "items",
            "plural_path": "items",
            "fields": [{"name": "title", "type": "string"}, {"name": "note", "type": "string"}],
        }
    ],
    "auth": {
        "enabled": True,
        "roles": [{"name": "admin", "label": "Admin"}],
        "permissions": [
            {"entity": "Item", "operation": op, "roles": ["admin"]}
            for op in ("list", "get", "create", "update", "delete", "replace", "head")
        ],
    },
}


def spec(**patch: Any) -> Spec:
    d = copy.deepcopy(BASE)
    for k, v in patch.items():
        if callable(v):
            v(d)
        else:
            d[k] = v
    return Spec.model_validate(d)


def flags(after: Spec, before: Spec | None = None, **kw: Any) -> list[str]:
    return risk_flags(before or spec(), after, **kw)


def test_no_change_no_flags() -> None:
    assert flags(spec()) == []


def test_flag_auth() -> None:
    assert flags(spec(auth=lambda d: d["auth"].update(jwt_algorithm="HS512"))) == ["auth"]
    assert "auth" in flags(spec(auth=lambda d: d["auth"]["permissions"].pop()))


def test_flag_tenancy() -> None:
    assert flags(spec(auth=lambda d: d["auth"].update(multi_tenant=True))) == ["tenancy"]


def test_flag_money() -> None:
    pay = {"enabled": True, "provider": "stripe"}
    assert "money" in flags(spec(payments=pay))
    after = spec(entities=lambda d: d["entities"][0]["fields"].append({"name": "price", "type": "decimal"}))
    assert flags(after) == ["money"]


def test_flag_public_endpoints() -> None:
    after = spec(auth=lambda d: d["auth"]["permissions"].pop(0))
    assert "public_endpoints" in flags(after)
    assert "public_endpoints" in flags(spec(auth=lambda d: d["auth"].update(enabled=False)))
    # tightening is not a new public endpoint
    assert "public_endpoints" not in flags(spec(), before=after)


def test_flag_data_deletion() -> None:
    assert "data_deletion" in flags(spec(entities=[]))
    assert "data_deletion" in flags(spec(entities=lambda d: d["entities"][0]["fields"].pop()))
    changed = spec(entities=lambda d: d["entities"][0]["fields"][1].update(type="int"))
    assert "data_deletion" in flags(changed)
    assert "data_deletion" in flags(spec(auth=lambda d: d["auth"].update(deletion_mode="hard")))
    # adding a field deletes nothing
    added = spec(entities=lambda d: d["entities"][0]["fields"].append({"name": "x", "type": "string"}))
    assert "data_deletion" not in flags(added)


def test_flag_data_deletion_soft_delete_off_and_cascade() -> None:
    before = spec(entities=lambda d: d["entities"][0]["options"].update(soft_delete=True) if "options" in d["entities"][0] else d["entities"][0].update(options={"soft_delete": True}))
    assert "data_deletion" in flags(spec(), before=before)


def test_flag_new_egress() -> None:
    smtp = {"host": "smtp.example.com", "from_email": "a@example.com", "from_name": "A"}
    assert "new_egress" in flags(spec(auth=lambda d: d["auth"].update(smtp=smtp)))
    assert "new_egress" in flags(spec(storage={"enabled": True, "bucket": "b"}))
    hooks = {"enabled": True, "trusted_authors_only": True, "webhook_hosts": ["h.example.com"]}
    assert "new_egress" in flags(spec(hook_effects=hooks))
    # removing egress is not new egress
    assert "new_egress" not in flags(spec(), before=spec(storage={"enabled": True, "bucket": "b"}))


def test_flag_new_dependencies_and_order() -> None:
    assert flags(spec(), dependencies=["left-pad"]) == ["new_dependencies"]
    assert flags(spec(), dependencies=["", "  "]) == []
    after = spec(
        auth=lambda d: d["auth"].update(multi_tenant=True, jwt_algorithm="HS512"),
        payments={"enabled": True},
    )
    assert flags(after, dependencies=["x"]) == ["auth", "tenancy", "money", "new_egress", "new_dependencies"]


def test_flags_deterministic() -> None:
    a = spec(entities=[], payments={"enabled": True})
    assert flags(a) == flags(a)


def _s(**kw: Any) -> Settings:
    return Settings(**kw)


def test_policy_defaults() -> None:
    p = effective_policy(_s())
    assert p.ttl["A"].days == 7 and p.ttl["B"].total_seconds() == 24 * 3600
    assert p.min_role == {"A": "editor", "B": "editor", "C": "editor", "D": "owner", "E": "owner"}
    assert not p.auto_plan_small_edit


def test_settings_cannot_relax_b_to_d() -> None:
    fake = SimpleNamespace(
        ai_approval_roles={"D": "editor", "E": "viewer", "B": "nobody", "C": None},
        ai_approval_ttl_hours=10_000,
        ai_approval_ttl_plan_hours=-5,
        ai_approval_auto_plan_small_edit="yes",
    )
    p = effective_policy(fake)  # type: ignore[arg-type]
    assert p.min_role["D"] == "owner" and p.min_role["E"] == "owner"
    assert p.min_role["B"] == "editor" and p.min_role["C"] == "editor"
    assert p.ttl["B"].days == 7  # clamped
    assert p.ttl["A"].total_seconds() == 60  # clamped to the minimum
    assert p.auto_plan_small_edit is False  # only the literal True counts


def test_settings_may_only_raise_the_floor() -> None:
    fake = SimpleNamespace(ai_approval_roles={"B": "owner", "A": "owner"})
    p = effective_policy(fake)  # type: ignore[arg-type]
    assert p.min_role["B"] == "owner" and p.min_role["A"] == "owner"


def test_junk_settings_fall_back() -> None:
    fake = SimpleNamespace(ai_approval_ttl_hours="soon", ai_approval_ttl_plan_hours=float("nan"))
    p = effective_policy(fake)  # type: ignore[arg-type]
    assert p.ttl["B"].total_seconds() == 24 * 3600 and p.ttl["A"].days == 7


@pytest.mark.parametrize("kind,owner", [("A", False), ("B", False), ("C", False), ("D", True), ("E", True)])
def test_owner_only_kinds(kind: str, owner: bool) -> None:
    assert requires_owner(kind, {}) is owner


@pytest.mark.parametrize(
    "payload",
    [
        {"hook": "x"},
        {"effects": ["email"]},
        {"hooks": []},
        {"hook_effects": {"enabled": True}},
        {"change": {"ops": [{"set": {"effects": []}}]}},
        {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}},  # too deep to inspect: treated as sensitive
    ],
)
def test_hook_payload_forces_owner_even_for_editor_kinds(payload: dict[str, Any]) -> None:
    assert requires_owner("B", payload) is True
    assert requires_owner("C", payload) is True


def test_plain_payload_stays_editor() -> None:
    assert requires_owner("B", {"summary": "add a field", "ops": [{"op": "add_field"}]}) is False


def test_policy_is_frozen() -> None:
    p = effective_policy(_s())
    assert isinstance(p, ApprovalPolicy)
    with pytest.raises(Exception):
        p.auto_plan_small_edit = True  # type: ignore[misc]
