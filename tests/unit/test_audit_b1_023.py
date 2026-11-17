"""Audit B1-023: agent state-machine access changes, plan-extension dead ends, weaken_access_rule."""

import copy
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core.spec_models import Spec
from app.services.agent import approved_effects, approval_service
from app.services.agent import tools as agent_tools
from app.services.agent.contract import ApprovalKind
from app.services.agent.tools import spec_tools
from app.services.agent.tools.read_tools import authoring_guide
from tests.e2e.hooks_support import example_spec
from tests.unit.test_agent_tools import PLAN, make_ctx

SM_PLAN = PLAN.__class__(PLAN.plan_id, entities=frozenset({"Invoice"}), hooks=PLAN.hooks, zones=PLAN.zones,
                         dependencies=PLAN.dependencies)


def _sm() -> dict[str, Any]:
    return copy.deepcopy(example_spec()["state_machines"][0])


def _patch(monkeypatch: pytest.MonkeyPatch, rows: dict[str, list[dict[str, Any]]]) -> None:
    async def section(ctx: Any, name: str) -> list[dict[str, Any]]:
        return rows.get(name, [])

    monkeypatch.setattr(spec_tools, "_current_section", section)
    monkeypatch.setattr(spec_tools, "_base_section", section)  # B1-005: base = draft here

    async def apply(*a: Any, **k: Any) -> Any:
        raise AssertionError("must not write the draft")

    monkeypatch.setattr(spec_tools, "add_draft_op", apply)


async def test_f0197_dropping_transition_roles_needs_owner_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _sm()
    _patch(monkeypatch, {"state_machines": [cur]})
    new = _sm()
    for t in new["transitions"]:
        t.pop("roles", None)  # the agent resends the machine without roles -> open to every updater
    r = await agent_tools.execute(make_ctx(plan=SM_PLAN), "set_section", {"section": "state_machines", "items": [new]})
    assert r.approval is not None and r.approval.kind == ApprovalKind.D, (r.failures, r.approval)
    assert r.data["executed"] is False


async def test_f0197_auto_flip_needs_owner_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _sm()
    _patch(monkeypatch, {"state_machines": [cur]})
    new = _sm()
    next(t for t in new["transitions"] if t["name"] == "pay")["auto"] = True
    r = await agent_tools.execute(make_ctx(plan=SM_PLAN), "set_section", {"section": "state_machines", "items": [new]})
    assert r.approval is not None and r.approval.kind == ApprovalKind.D, r.failures


def test_f0197_risk_flags_see_transition_roles() -> None:
    before = Spec.model_validate(example_spec())
    raw = example_spec()
    for t in raw["state_machines"][0]["transitions"]:
        if t["name"] == "pay":
            t["roles"] = []
    after = Spec.model_validate(raw)
    assert "auth" in approval_service.risk_flags(before, after)
    assert "auth" not in approval_service.risk_flags(before, before)


async def test_f0203_guide_example_and_unchanged_machine_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = authoring_guide()["state_machine"]["example"]
    _patch(monkeypatch, {})
    seen: list[Any] = []

    async def apply(ctx: Any, tool: str, op: str, payload: dict[str, Any], note: str) -> Any:
        seen.append(payload)
        return spec_tools.ToolResult(ok=True)

    monkeypatch.setattr(spec_tools, "_apply", apply)
    plan = PLAN.__class__(PLAN.plan_id, entities=frozenset({ex["entity"]}), hooks=PLAN.hooks, zones=PLAN.zones,
                          dependencies=PLAN.dependencies)
    r = await agent_tools.execute(make_ctx(plan=plan), "set_section", {"section": "state_machines", "items": [ex]})
    assert r.ok, r.failures
    # an existing machine (dumped with roles) resent unchanged is fine too
    cur = _sm()
    _patch(monkeypatch, {"state_machines": [cur]})
    monkeypatch.setattr(spec_tools, "_apply", apply)
    r = await agent_tools.execute(make_ctx(plan=SM_PLAN), "set_section", {"section": "state_machines", "items": [_sm()]})
    assert r.ok, r.failures
    assert len(seen) == 2


async def test_f0203_other_security_keys_in_state_machines_still_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {})
    sm = _sm()
    sm["permissions"] = ["x"]
    r = await agent_tools.execute(make_ctx(plan=SM_PLAN), "set_section", {"section": "state_machines", "items": [sm]})
    assert r.failures and r.failures[0].rule_id == "tool_s_bang"


async def test_f0198_empty_plan_and_section_item_are_hard_refusals(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {"settings": [{"key": "k1", "type": "int", "default": 1}]})
    r = await agent_tools.execute(make_ctx(), "set_section", {
        "section": "settings", "items": [{"key": "k1", "type": "int", "default": 9}]})
    assert r.needs_plan_extension is None and r.failures and r.failures[0].rule_id == "plan_scope"
    empty = PLAN.__class__(uuid.uuid4())
    r = await agent_tools.execute(make_ctx(plan=empty), "add_entity", {"entity": {"name": "X"}})
    assert r.needs_plan_extension is None and r.failures and r.failures[0].rule_id == "plan_scope"


def _spec_without_rows() -> Spec:
    raw = example_spec()
    raw["auth"]["permissions"] = [p for p in raw["auth"]["permissions"] if p["entity"] != "Invoice"]
    return Spec.model_validate(raw)


async def test_f0200_weaken_on_public_operation_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec_without_rows()

    async def rs(session: Any, rid: Any, pid: Any) -> Spec:
        return spec

    monkeypatch.setattr(approved_effects, "run_spec", rs)
    run = cast(Any, SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4()))
    approval = cast(Any, SimpleNamespace(kind="D", payload={
        "op_type": "weaken_access_rule", "entity": "Invoice", "role": "clerk", "action": "list"}))
    added: list[Any] = []

    async def add(*a: Any, **k: Any) -> int:
        added.append(a)
        return 1

    monkeypatch.setattr(approved_effects, "add_draft_op", add)
    out = await approved_effects.execute(cast(Any, None), run, approval)
    assert out["executed"] is False and not added, out
    # an unknown action on the entity is refused too
    approval.payload = {**approval.payload, "action": "no_such_op"}
    out = await approved_effects.execute(cast(Any, None), run, approval)
    assert out["executed"] is False and not added, out


async def test_f0200_weaken_with_existing_row_still_adds_the_role(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = Spec.model_validate(example_spec())

    async def rs(session: Any, rid: Any, pid: Any) -> Spec:
        return spec

    monkeypatch.setattr(approved_effects, "run_spec", rs)
    run = cast(Any, SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4()))
    name, op = await approved_effects._d_op(None, run, {  # type: ignore[arg-type]
        "op_type": "weaken_access_rule", "entity": "Invoice", "role": "approver", "action": "create"})
    perm = next(p for p in op["spec"]["auth"]["permissions"] if p["entity"] == "Invoice" and p["operation"] == "create")
    assert "approver" in perm["roles"] and "clerk" in perm["roles"]

