"""Audit B1-005: F-0936 empty-roles weaken, F-0937 base-spec compare, F-0938 `when` change, F-0939 coverage."""

import copy
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core.spec_models import Spec
from app.services.agent import approval_service, approved_effects
from app.services.agent import tools as agent_tools
from app.services.agent.contract import ApprovalKind
from app.services.agent.tools import spec_tools
from tests.e2e.hooks_support import example_spec
from tests.unit.test_agent_tools import make_ctx
from tests.unit.test_audit_b1_023 import SM_PLAN


def _sm() -> dict[str, Any]:
    return copy.deepcopy(example_spec()["state_machines"][0])


def _patch(monkeypatch: pytest.MonkeyPatch, cur: list[dict[str, Any]], base: list[dict[str, Any]]) -> None:
    async def section(ctx: Any, name: str) -> list[dict[str, Any]]:
        return cur

    async def base_section(ctx: Any, name: str) -> list[dict[str, Any]]:
        return base

    monkeypatch.setattr(spec_tools, "_current_section", section)
    monkeypatch.setattr(spec_tools, "_base_section", base_section, raising=False)

    async def apply(*a: Any, **k: Any) -> Any:
        raise AssertionError("must not write the draft")

    monkeypatch.setattr(spec_tools, "add_draft_op", apply)


async def _set(items: list[dict[str, Any]]) -> Any:
    return await agent_tools.execute(make_ctx(plan=SM_PLAN), "set_section", {"section": "state_machines", "items": items})


def _run(spec: Spec, monkeypatch: pytest.MonkeyPatch) -> Any:
    async def rs(session: Any, rid: Any, pid: Any) -> Spec:
        return spec

    monkeypatch.setattr(approved_effects, "run_spec", rs)
    return cast(Any, SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4()))


async def test_f0936_weaken_on_empty_roles_row_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = example_spec()
    row = next(p for p in raw["auth"]["permissions"] if p["entity"] == "Invoice" and p["operation"] == "list")
    row["roles"] = []
    run = _run(Spec.model_validate(raw), monkeypatch)
    approval = cast(Any, SimpleNamespace(kind="D", payload={
        "op_type": "weaken_access_rule", "entity": "Invoice", "role": "clerk", "action": "list"}))
    added: list[Any] = []

    async def add(*a: Any, **k: Any) -> int:
        added.append(a)
        return 1

    monkeypatch.setattr(approved_effects, "add_draft_op", add)
    out = await approved_effects.execute(cast(Any, None), run, approval)
    assert out["executed"] is False and not added, out


async def test_f0937_remove_then_readd_open_machine_needs_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    base = _sm()
    _patch(monkeypatch, [], [base])  # call 1 dropped the machine from the draft; the base still has it
    new = _sm()
    for t in new["transitions"]:
        t["roles"] = []
    r = await _set([new])
    assert r.approval is not None and r.approval.kind == ApprovalKind.D, r.failures


async def test_f0937_new_open_transition_in_existing_machine_needs_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _sm()
    _patch(monkeypatch, [cur], [cur])
    new = _sm()
    to = new["transitions"][0]["to_state"]
    new["transitions"].append({"name": "force_pay", "from_states": [new["transitions"][0]["from_states"][0]],
                               "to_state": to, "roles": []})
    r = await _set([new])
    assert r.approval is not None and r.approval.kind == ApprovalKind.D, r.failures


async def test_f0937_unchanged_machine_still_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _sm()
    _patch(monkeypatch, [cur], [cur])

    async def apply(*a: Any, **k: Any) -> Any:
        return spec_tools.ToolResult(ok=True)

    monkeypatch.setattr(spec_tools, "_apply", apply)
    r = await _set([_sm()])
    assert r.ok, r.failures


def test_f0938_weakened_when_is_loosening() -> None:
    f = approval_service.transition_loosened
    base = {"roles": ["a"], "auto": False, "when": "amount <= 50000", "from_states": ["x"]}
    assert f(base, {**base, "when": "true"})
    assert f(base, {**base, "when": "amount <= 99999999"})
    assert f(base, {**base, "when": None})  # F-0939: dropped
    assert not f(base, dict(base))
    assert not f(base, {**base, "when": " amount  <=  50000 "})
    assert f(base, {**base, "from_states": ["x", "y"]})
    assert not f({**base, "when": None}, {**base, "when": None})


def test_f0938_risk_flags_auth_for_when_change() -> None:
    raw = example_spec()
    tr = next(t for t in raw["state_machines"][0]["transitions"] if t["name"] == "pay")
    tr["when"] = "total <= 50000"
    before = Spec.model_validate(raw)
    tr["when"] = "true"
    after = Spec.model_validate(raw)
    assert "auth" in approval_service.risk_flags(before, after)
    tr["when"] = None
    assert "auth" in approval_service.risk_flags(before, Spec.model_validate(raw))


async def test_f0939_approved_set_section_state_machines_returns_op(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run(Spec.model_validate(example_spec()), monkeypatch)
    items = [_sm()]
    name, op = await approved_effects._d_op(None, run, {"op_type": "set_section", "section": "state_machines", "items": items})  # type: ignore[arg-type]
    assert name == "set_section" and op == {"section": "state_machines", "items": items}


async def test_f0939_approved_set_section_other_section_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run(Spec.model_validate(example_spec()), monkeypatch)
    with pytest.raises(approved_effects.AppError) as ei:
        await approved_effects._d_op(None, run, {"op_type": "set_section", "section": "hooks", "items": []})  # type: ignore[arg-type]
    assert ei.value.code == "approval_not_applicable" and ei.value.status_code == 422
