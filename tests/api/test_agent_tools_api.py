"""B3-2 API tests: the agent tools against a real database (ops log, dependency policy, hook author)."""

import uuid
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.core.generator import generate
from app.core.spec_models import Spec
from app.models.agent import AiDraftOp, AiRun
from app.models.dependency_policy import DependencyRequest
from app.models.project import Project
from app.models.spec_op import SpecOp
from app.services.agent import tools as agent_tools
from app.services.agent.contract import Actor, ApprovalKind, Phase, Plan, ToolContext
from app.services.agent.draft import run_spec, spec_seq
from app.services.spec_service import SpecService
from tests.api._auth_helpers import make_project

PLAN = Plan(
    uuid.uuid4(),
    entities=frozenset({"Item"}),
    hooks=frozenset({"check_item"}),
    dependencies=frozenset({"left-pad", "orjson"}),
)
HOOK = {
    "name": "check_item",
    "point": "Item.validate",
    "kind": "pure",
    "input": {"name": "ItemInput", "fields": [{"name": "title", "type": "string", "required": True}]},
    "output": {"name": "ItemResult", "fields": [{"name": "valid", "type": "bool", "required": True}]},
}


async def _ctx(
    client: AsyncClient, session: AsyncSession, worktree: Path | None = None, plan: Plan | None = PLAN
) -> ToolContext:
    pid = uuid.UUID(await make_project(client))
    project = await session.get(Project, pid)
    assert project is not None
    user = client.user  # type: ignore[attr-defined]
    base = await SpecService(session).assemble(pid)
    run = AiRun(  # a build-phase run whose plan is approved: its spec edits go to the draft (H2)
        project_id=pid, created_by=user.id, goal="g", state="running", phase="build",
        plan={"base_spec_seq": await spec_seq(session, pid), "base_spec": base.model_dump(mode="json")},
    )
    session.add(run)
    await session.commit()
    return ToolContext(
        session=session, settings=get_settings(), org_id=project.organization_id, project_id=pid,
        run_id=run.id, actor=Actor("agent", user.id), phase=Phase.build, plan=plan,
        worktree=str(worktree) if worktree else None,
    )  # fmt: skip


async def test_s_tools_write_the_run_draft_not_the_op_log(client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as s:
        ctx = await _ctx(client, s)
        r = await agent_tools.execute(ctx, "add_entity", {"entity": {"name": "Item", "fields": [{"name": "title", "type": "string"}]}})
        assert r.ok, r.failures
        r = await agent_tools.execute(ctx, "add_field", {"entity": "Item", "field": {"name": "qty", "type": "integer"}})
        assert r.ok, r.failures
        r = await agent_tools.execute(ctx, "add_field", {"entity": "Item", "field": {"name": "qty", "type": "integer"}})
        assert not r.ok and r.failures[0].rule_id == "conflict"  # duplicate -> RuleFailure, not an exception
        r = await agent_tools.execute(ctx, "add_field", {"entity": "Item", "field": {"name": "x", "type": "nonsense"}})
        assert not r.ok
        r = await agent_tools.execute(ctx, "add_entity", {"entity": {"name": "Other"}})
        assert r.needs_plan_extension == ("entity", "Other")
        live_ops = (await s.execute(select(SpecOp).where(SpecOp.project_id == ctx.project_id))).scalars().all()
        assert live_ops == [] and (await SpecService(s).assemble(ctx.project_id)).entities == []  # live untouched
        drafts = (await s.execute(select(AiDraftOp).where(AiDraftOp.run_id == ctx.run_id).order_by(AiDraftOp.seq))).scalars().all()
        assert [o.op_type for o in drafts] == ["add_entity", "add_field"]
        spec = await run_spec(s, ctx.run_id, ctx.project_id)
        assert [f.name for f in spec.entities[0].fields] == ["title", "qty"]
        got = await agent_tools.execute(ctx, "get_spec", {})
        assert got.data["untrusted_data"]["entities"][0]["name"] == "Item"


async def test_s_bang_leaves_spec_untouched(client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as s:
        ctx = await _ctx(client, s)
        await agent_tools.execute(ctx, "add_entity", {"entity": {"name": "Item"}})
        r = await agent_tools.execute(ctx, "remove_entity", {"name": "Item", "reason": "cleanup"})
        assert r.ok and r.approval is not None and r.approval.kind is ApprovalKind.D
        r = await agent_tools.execute(ctx, "set_section", {"section": "authorization", "items": []})
        assert r.failures[0].rule_id == "tool_s_bang"
        spec = await run_spec(s, ctx.run_id, ctx.project_id)
        assert [e.name for e in spec.entities] == ["Item"]


async def test_request_dependency(client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as s:
        ctx = await _ctx(client, s)
        r = await agent_tools.execute(ctx, "request_dependency", {"name": "orjson", "version": "3.10.0", "reason": "speed"})
        assert r.ok and r.data["status"] == "active" and r.data["installed"] is False and r.approval is None
        args = {"name": "Left_Pad", "version": "1.2.3", "reason": "padding"}
        r = await agent_tools.execute(ctx, "request_dependency", args)
        assert r.ok and r.data["status"] == "pending" and r.approval is not None
        again = await agent_tools.execute(ctx, "request_dependency", args)
        assert again.data["new_request"] is False
        rows = (await s.execute(select(DependencyRequest).where(DependencyRequest.project_id == ctx.project_id))).scalars().all()
        assert len(rows) == 1 and rows[0].status == "pending"
        r = await agent_tools.execute(ctx, "request_dependency", {"name": "evil", "version": "1.0.0", "reason": "x"})
        assert r.needs_plan_extension == ("dependency", "evil")
        r = await agent_tools.execute(ctx, "request_dependency", {"name": "left-pad", "version": "not a version", "reason": "x"})
        assert not r.ok and r.failures[0].rule_id == "invalid_dependency"


async def test_hook_flow_records_author_ai(client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path) -> None:
    async with session_factory() as s:
        ctx = await _ctx(client, s, worktree=tmp_path)
        await agent_tools.execute(ctx, "add_entity", {"entity": {"name": "Item", "fields": [{"name": "title", "type": "string"}]}})
        r = await agent_tools.execute(ctx, "create_custom_hook", {"name": "check_item", "purpose": "x"})
        assert r.failures[0].rule_id == "hook_not_declared"
        r = await agent_tools.execute(ctx, "set_section", {"section": "hooks", "items": [{**HOOK, "author": "trusted"}]})
        assert r.ok, r.failures
        spec = await run_spec(s, ctx.run_id, ctx.project_id)
        assert spec.hooks[0].author == "ai"  # the agent cannot declare itself trusted
        r = await agent_tools.execute(ctx, "create_custom_hook", {"name": "check_item", "purpose": "validate items"})
        assert r.ok and r.data["created"] is True and r.approval is not None and r.approval.kind is ApprovalKind.C
        stub = tmp_path / "app/custom/hooks/check_item.py"
        assert stub.is_file() and (tmp_path / "platform/hooks.json").is_file()
        before = stub.read_bytes()
        bad = await agent_tools.execute(ctx, "replace_function_body", {"hook": "check_item", "body": "import os\nreturn ItemResult(valid=True)"})
        assert not bad.ok and stub.read_bytes() == before
        good = await agent_tools.execute(ctx, "replace_function_body", {"hook": "check_item", "body": "return ItemResult(valid=len(data.title) > 0)"})
        assert good.ok, good.failures
        assert good.approval is not None and good.approval.payload["author"] == "ai"
        spec = await run_spec(s, ctx.run_id, ctx.project_id)
        assert spec.hooks[0].author == "ai"
        # the whole generated tree still agrees with the stub the tool wrote
        assert "app/custom/hooks/check_item.py" in generate(Spec.model_validate(spec.model_dump()))
        gates = await agent_tools.execute(ctx, "run_gates", {})
        assert not any(f.rule_id.startswith(("G0", "G1", "G2", "G5")) for f in gates.failures), gates.failures
