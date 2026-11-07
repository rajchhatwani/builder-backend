"""CP-C: the real tools, approvals and gates driven by a scripted model over a real draft workspace."""

import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.agent_runs import agent_deps
from app.config import Settings
from app.main import app
from app.services import workspace_service
from app.services.agent.run_service import AgentDeps
from app.services.agent.wiring import Approvals, Gates, Toolbox
from app.services.ai.base import (
    Completion,
    CompletionRequest,
    ModelProvider,
    StreamEvent,
    ToolCall,
    Usage,
)
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
Factory = async_sessionmaker[AsyncSession]


class Script(ModelProvider):
    name = "script"

    def __init__(self, steps: list[Completion]) -> None:
        self.steps, self.requests = steps, []  # type: ignore[var-annotated]

    async def complete(self, model: str, request: CompletionRequest) -> Completion:
        self.requests.append(request)
        return self.steps[min(len(self.requests), len(self.steps)) - 1]

    def stream(self, model: str, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError


def call(tool: str, /, **inp: Any) -> Completion:
    return Completion(
        model="m", text="", tool_calls=[ToolCall(id=f"c-{uuid.uuid4().hex[:8]}", name=tool, input=inp)],
        usage=Usage(input_tokens=100, output_tokens=50), stop_reason="tool_use",
    )  # fmt: skip


@pytest.fixture
def ws_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str) -> Settings:
    s = Settings(environment="test", workspace_root=str(tmp_path / "ws"), workspace_db_admin_url=SecretStr(database_url))
    monkeypatch.setattr(workspace_service, "get_settings", lambda: s)
    return s


def install(provider: Script, gates: Gates | None = None) -> None:
    deps = AgentDeps(
        toolbox=Toolbox(), approvals=Approvals(), gates=gates or Gates(), provider_factory=lambda key: provider
    )
    app.dependency_overrides[agent_deps] = lambda: deps


_MADE: list[tuple[str, str]] = []


@pytest.fixture(autouse=True)
async def _cleanup(client: AsyncClient) -> Any:
    yield
    app.dependency_overrides.pop(agent_deps, None)
    # Discard every draft so no checkpoint database (bbcp_*) outlives the test.
    while _MADE:
        pid, ws = _MADE.pop()
        await client.delete(f"/projects/{pid}/workspaces/{ws}")


_FACTORY: Any = None


@pytest.fixture(autouse=True)
def _capture_factory(session_factory: Factory) -> None:
    global _FACTORY
    _FACTORY = session_factory


async def _draft_count(rid: str) -> int:
    from sqlalchemy import func, select

    from app.models.agent import AiDraftOp

    async with _FACTORY() as s:
        q = select(func.count()).select_from(AiDraftOp).where(AiDraftOp.run_id == uuid.UUID(rid))
        return int((await s.execute(q)).scalar_one())


async def _setup(client: AsyncClient) -> tuple[str, str, str]:
    pid = await make_project(client)
    ws = await client.post(f"/projects/{pid}/workspaces", json={"name": "draft"})
    assert ws.status_code == 201, ws.text
    _MADE.append((pid, ws.json()["id"]))
    run = await client.post(f"/projects/{pid}/agent/runs", json={"goal": "invoices", "workspace_id": ws.json()["id"]})
    assert run.status_code == 201, run.text
    return pid, ws.json()["id"], run.json()["id"]


async def _resume(client: AsyncClient, pid: str, rid: str, allow_stop: bool = False) -> dict[str, Any]:
    r = await client.post(f"/projects/{pid}/agent/runs/{rid}/resume")
    assert r.status_code == 200, r.text
    body = dict(r.json())
    if body["state"] == "stopped" and not allow_stop:
        full = (await client.get(f"/projects/{pid}/agent/runs/{rid}")).json()
        pytest.fail(f"stopped: {body['stop_code']} {body['stop_detail']} steps={full['steps'][-3:]}")
    return body


async def _decide(client: AsyncClient, pid: str, approve: bool = True) -> dict[str, Any]:
    pend = (await client.get(f"/projects/{pid}/agent/approvals?state=pending")).json()
    items = pend["items"] if isinstance(pend, dict) else pend
    assert len(items) == 1, items
    r = await client.post(
        f"/projects/{pid}/agent/approvals/{items[0]['id']}/decision", json={"approve": approve}
    )
    assert r.status_code == 200, r.text
    return dict(items[0])


PLAN = {"entities": ["Invoice"], "hooks": [], "zones": [], "dependencies": []}


async def test_plan_build_gates_approve_apply(client: AsyncClient, ws_settings: Settings) -> None:
    pid, _ws, rid = await _setup(client)
    provider = Script([
        call("finish", summary="plan", plan=PLAN),
        call("add_entity", entity={"name": "Invoice"}),
        call("finish", summary="built"),
        call("finish", summary="apply"),
    ])  # fmt: skip
    install(provider)

    run = await _resume(client, pid, rid)
    assert run["state"] == "awaiting_approval" and run["phase"] == "plan"
    a = await _decide(client, pid)
    assert a["kind"] == "A"

    run = await _resume(client, pid, rid)  # build: add_entity then finish -> gates -> C approval
    assert run["phase"] == "build", run
    assert run["state"] == "awaiting_approval", run
    c = await _decide(client, pid)
    assert c["kind"] == "C"
    ents = (await client.get(f"/projects/{pid}/entities")).json()
    assert "Invoice" not in str(ents)  # H2: approved, but not applied yet; the live spec is untouched

    run = await _resume(client, pid, rid)  # approval still valid -> apply phase -> finish -> applied
    assert run["phase"] == "apply" and run["state"] == "applied", run
    assert "Invoice" in str((await client.get(f"/projects/{pid}/entities")).json())
    assert await _draft_count(rid) == 0
    ops = (await client.get(f"/projects/{pid}/spec/ops")).json()
    assert str(ops).count("add_entity") == 1  # applied exactly once, by the agent
    assert any((s["output"] or {}).get("draft") == "applied" for s in await _steps(client, pid, rid))


async def test_outside_plan_is_refused_and_asks_to_extend(client: AsyncClient, ws_settings: Settings) -> None:
    pid, _ws, rid = await _setup(client)
    install(Script([
        call("finish", summary="plan", plan=PLAN),
        call("add_entity", entity={"name": "Payroll"}),
    ]))  # fmt: skip
    await _resume(client, pid, rid)
    await _decide(client, pid)
    run = await _resume(client, pid, rid)
    assert run["state"] == "awaiting_approval"
    ents = (await client.get(f"/projects/{pid}/entities")).json()
    assert "Payroll" not in str(ents)  # nothing was created
    pending = (await client.get(f"/projects/{pid}/agent/approvals?state=pending")).json()
    items = pending["items"] if isinstance(pending, dict) else pending
    assert items and "extend plan" in items[0]["subject"]


async def test_approved_extension_widens_the_plan_so_the_retry_succeeds(
    client: AsyncClient, ws_settings: Settings
) -> None:
    """Found by the first real run: an approved 'extend plan' used to be ignored and the agent looped."""
    pid, _ws, rid = await _setup(client)
    payroll = {"name": "Payroll", "fields": [{"name": "title", "type": "string"}]}
    install(Script([
        call("finish", summary="plan", plan=PLAN),
        call("add_entity", entity=payroll),
        call("add_entity", entity=payroll),
    ]))  # fmt: skip
    await _resume(client, pid, rid)
    await _decide(client, pid)
    run = await _resume(client, pid, rid)
    assert run["state"] == "awaiting_approval"  # refused: outside the plan, asks to extend
    pend = await _pending(client, pid)
    assert pend["payload"]["extend"] == {"kind": "entity", "name": "Payroll"}
    await _decide(client, pid)
    run = await _resume(client, pid, rid, allow_stop=True)
    steps = await _steps(client, pid, rid)
    adds = [s for s in steps if s.get("tool_name") == "add_entity"]
    assert [s["ok"] for s in adds][:2] == [False, True], adds  # later repeats hit the existing entity


async def test_run_gates_tool_passes_on_a_hookless_draft(client: AsyncClient, ws_settings: Settings) -> None:
    """Found by the first real run: run_gates failed every project without hooks (G7.manifest)."""
    pid, _ws, rid = await _setup(client)
    install(Script([
        call("finish", summary="plan", plan={"entities": ["Item"], "hooks": [], "zones": [], "dependencies": []}),
        call("add_entity", entity=ITEM),
        call("run_gates"),
    ]))  # fmt: skip
    await _resume(client, pid, rid)
    await _decide(client, pid)
    await _resume(client, pid, rid, allow_stop=True)
    gates = [s for s in await _steps(client, pid, rid) if s.get("tool_name") == "run_gates"]
    assert gates and gates[0]["ok"] is True, gates


HOOK = {
    "name": "h1",
    "point": "Item.validate",
    "kind": "pure",
    "input": {"name": "ItemInput", "fields": [{"name": "title", "type": "string", "required": True}]},
    "output": {"name": "ItemResult", "fields": [{"name": "valid", "type": "bool", "required": True}]},
}
HOOK_PLAN = {"entities": ["Item"], "hooks": ["h1"], "zones": [], "dependencies": []}
ITEM = {"name": "Item", "fields": [{"name": "title", "type": "string"}]}


async def _pending(client: AsyncClient, pid: str) -> dict[str, Any]:
    pend = (await client.get(f"/projects/{pid}/agent/approvals?state=pending")).json()
    items = pend["items"] if isinstance(pend, dict) else pend
    assert len(items) == 1, items
    return dict(items[0])


async def _steps(client: AsyncClient, pid: str, rid: str) -> list[dict[str, Any]]:
    return list((await client.get(f"/projects/{pid}/agent/runs/{rid}?limit=500")).json()["steps"])


async def test_hook_review_does_not_skip_gates_and_final_c_is_owner_only(
    client: AsyncClient, client_for: ClientFor, ws_settings: Settings
) -> None:
    pid, _ws, rid = await _setup(client)
    editor = await client_for("ed@example.com")
    await add_to_project_org(pid, "ed@example.com")
    m = await client.post(f"/projects/{pid}/members", json={"email": "ed@example.com", "role": "editor"})
    assert m.status_code == 201, m.text
    install(Script([
        call("finish", summary="plan", plan=HOOK_PLAN),
        call("add_entity", entity=ITEM),
        call("set_section", section="hooks", items=[HOOK]),
        call("create_custom_hook", name="h1", purpose="validate"),
        call("replace_function_body", hook="h1", body="return ItemResult(valid=len(data.title) > 0)"),
        call("finish", summary="built"),
    ]))  # fmt: skip
    await _resume(client, pid, rid)
    assert (await _decide(client, pid))["kind"] == "A"
    run = await _resume(client, pid, rid)  # replace_function_body asks for a hook review (C)
    assert run["state"] == "awaiting_approval" and run["phase"] == "build", run
    mid = await _decide(client, pid)
    assert mid["kind"] == "C" and mid["payload"].get("final") is None
    run = await _resume(client, pid, rid)  # H1: a mid-run review resumes BUILD, never applies; finish -> gates
    assert run["phase"] == "build" and run["state"] == "awaiting_approval", run
    final = await _pending(client, pid)
    assert final["kind"] == "C" and final["payload"]["final"] is True
    assert len(final["payload"]["gate_report_hash"]) == 64
    assert final["payload"]["hooks"] == [{"name": "h1", "author": "ai"}]
    assert any(f.startswith("app/") for f in final["payload"]["files"])
    assert final["payload"]["gates_green"] is True
    diff = final["payload"]["spec_diff"]  # what the reviewer is approving, from the draft vs the base
    assert diff and all("section" in d for d in diff), diff
    # M5: an AI hook makes the final review owner-only
    r = await editor.post(f"/projects/{pid}/agent/approvals/{final['id']}/decision", json={"approve": True})
    assert r.status_code == 403, r.text
    await _decide(client, pid)
    run = await _resume(client, pid, rid)
    assert run["state"] == "applied" and run["phase"] == "apply", run


async def _to_final_review(client: AsyncClient) -> tuple[str, str]:
    pid, _ws, rid = await _setup(client)
    install(Script([
        call("finish", summary="plan", plan=PLAN),
        call("add_entity", entity={"name": "Invoice"}),
        call("finish", summary="built"),
    ]))  # fmt: skip
    await _resume(client, pid, rid)
    await _decide(client, pid)
    run = await _resume(client, pid, rid)
    assert run["state"] == "awaiting_approval" and run["phase"] == "build", run
    assert "Invoice" not in str((await client.get(f"/projects/{pid}/entities")).json())  # H2: draft only
    return pid, rid


async def test_agent_edits_stay_in_the_draft_until_c_is_approved(client: AsyncClient, ws_settings: Settings) -> None:
    pid, rid = await _to_final_review(client)
    assert "Invoice" not in str((await client.get(f"/projects/{pid}/entities")).json())  # live untouched
    assert str((await client.get(f"/projects/{pid}/spec/ops")).json()).count("add_entity") == 0
    assert await _draft_count(rid) == 1
    final = await _pending(client, pid)
    assert final["payload"]["final"] is True and "risk_flags" in final


async def test_denied_final_review_discards_the_draft(client: AsyncClient, ws_settings: Settings) -> None:
    pid, rid = await _to_final_review(client)
    await _decide(client, pid, approve=False)
    run = await _resume(client, pid, rid, allow_stop=True)
    assert run["state"] == "stopped" and run["stop_code"] == "denied", run
    assert "Invoice" not in str((await client.get(f"/projects/{pid}/entities")).json())
    assert str((await client.get(f"/projects/{pid}/spec/ops")).json()).count("add_entity") == 0
    assert await _draft_count(rid) == 0
    assert any((s["output"] or {}).get("draft") == "discarded" for s in await _steps(client, pid, rid))


async def test_cancel_discards_the_draft(client: AsyncClient, ws_settings: Settings) -> None:
    pid, rid = await _to_final_review(client)
    r = await client.post(f"/projects/{pid}/agent/runs/{rid}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    assert "Invoice" not in str((await client.get(f"/projects/{pid}/entities")).json())
    assert await _draft_count(rid) == 0


async def test_person_edit_during_the_run_makes_apply_a_conflict(client: AsyncClient, ws_settings: Settings) -> None:
    pid, rid = await _to_final_review(client)
    assert (await client.post(f"/projects/{pid}/entities", json={"name": "Sneaky"})).status_code == 201
    await _decide(client, pid)  # C approved (the draft is unchanged, so the approval is still valid)
    run = await _resume(client, pid, rid, allow_stop=True)
    assert run["state"] == "stopped" and run["stop_code"] == "apply_conflict", (run["state"], run.get("stop_code"), run.get("stop_detail"))
    ents = str((await client.get(f"/projects/{pid}/entities")).json())
    assert "Sneaky" in ents and "Invoice" not in ents  # the person's edit stays, the draft was not applied
    assert any((s["output"] or {}).get("apply_conflict") for s in await _steps(client, pid, rid))
    assert await _draft_count(rid) == 0


async def test_discard_is_what_every_failure_path_calls(client: AsyncClient, ws_settings: Settings) -> None:
    from app.services.agent.run_service import discard_draft

    pid, rid = await _to_final_review(client)
    async with _FACTORY() as s:
        assert await discard_draft(s, uuid.UUID(rid)) == "discarded"
        assert await discard_draft(s, uuid.UUID(rid)) == "nothing"  # idempotent
    assert await _draft_count(rid) == 0
    assert "Invoice" not in str((await client.get(f"/projects/{pid}/entities")).json())


async def test_draft_is_invisible_to_other_projects(client: AsyncClient, ws_settings: Settings) -> None:
    from app.services.agent.draft import run_spec

    pid, rid = await _to_final_review(client)
    other = await make_project(client)
    async with _FACTORY() as s:
        mine = await run_spec(s, uuid.UUID(rid), uuid.UUID(pid))
        assert "Invoice" in [e.name for e in mine.entities]
        theirs = await run_spec(s, uuid.UUID(rid), uuid.UUID(other))  # a run id of another project: live only
        assert "Invoice" not in [e.name for e in theirs.entities]
    assert "Invoice" not in str((await client.get(f"/projects/{other}/entities")).json())


async def test_approval_goes_stale_when_the_draft_moves(client: AsyncClient, ws_settings: Settings) -> None:
    from app.services.agent.draft import add_draft_op

    pid, rid = await _to_final_review(client)
    await _decide(client, pid)  # final C approved on the draft as reviewed
    async with _FACTORY() as s:
        await add_draft_op(s, uuid.UUID(rid), uuid.UUID(pid), "add_entity", {"entity": {"name": "Invoice2"}})
    run = await _resume(client, pid, rid, allow_stop=True)
    assert run["state"] != "applied" and run["phase"] == "build", run
    assert any("no longer valid" in str(s["output"]) for s in await _steps(client, pid, rid))
    assert "Invoice" not in str((await client.get(f"/projects/{pid}/entities")).json())


async def test_worktree_edit_after_final_approval_makes_it_stale(client: AsyncClient, ws_settings: Settings) -> None:
    pid, rid = await _to_final_review(client)
    await _decide(client, pid)  # final C approved
    wt = Path(ws_settings.workspace_root or "") / pid / "wt"
    root = next(wt.iterdir())
    (root / "NOTES.txt").write_text("edited after the review\n")  # uncommitted, outside git HEAD
    run = await _resume(client, pid, rid, allow_stop=True)
    assert run["state"] != "applied" and run["phase"] == "build", run
    assert any("no longer valid" in str(s["output"]) for s in await _steps(client, pid, rid))
