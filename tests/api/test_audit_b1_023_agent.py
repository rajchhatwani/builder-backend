"""Audit B1-023: budget stop before apply, N4 sweep with consumed decisions, per-run changed-files baseline."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.config import get_settings
from app.models.agent import AiApproval, AiRun, AiStep
from app.models.workspace import Workspace, WorkspaceCheckpoint
from app.services.agent import wiring
from app.services.agent.sweeper import sweep_once
from tests.api._approval_hash import reviewer_sends_hash  # noqa: F401  (isort: skip)
from tests.api._auth_helpers import make_project
from tests.api.test_agent_approvals import _ask
from tests.api.test_agent_fb2a import PAST, _crashed_run, _deps
from tests.api.test_agent_runs import (
    FakeToolbox,
    Factory,
    ScriptedProvider,
    _new,
    _patch_run,
    _run,
    _url,
    finish,
    install as install,  # fixture re-export
)


async def test_f0199_apply_phase_is_not_stopped_by_the_step_budget(
    client: AsyncClient, install: Any, session_factory: Factory
) -> None:
    provider = ScriptedProvider(lambda n, r: finish(n))
    install(provider, FakeToolbox())
    pid = await make_project(client)
    rid = await _new(client, pid)
    # the build finish used the last allowed step; the owner approved the final review
    await _patch_run(session_factory, rid, state="running", phase="apply", steps_used=2, budgets={"max_steps": 2})
    await client.post(_url(pid, rid, "/resume"))
    run = await _run(session_factory, rid)
    assert run.stop_code != "budget_steps", (run.state, run.stop_code)


async def test_f0201_sweep_stops_a_run_whose_only_live_looking_rows_are_consumed(
    client: AsyncClient, session_factory: Factory
) -> None:
    pid = await make_project(client)
    rid = await _crashed_run(client, session_factory, pid, "awaiting_approval", PAST)
    plan_a = await _ask(session_factory, pid, uuid.UUID(rid), kind="A")
    final_c = await _ask(session_factory, pid, uuid.UUID(rid), kind="C")
    old = await _ask(session_factory, pid, uuid.UUID(rid), kind="A", payload={"summary": "older"})
    async with session_factory() as s:
        await s.execute(update(AiApproval).where(AiApproval.id == plan_a).values(state="approved"))
        await s.execute(update(AiApproval).where(AiApproval.id == old).values(state="superseded"))
        await s.execute(update(AiApproval).where(AiApproval.id == final_c).values(
            expires_at=datetime.now(UTC) - timedelta(hours=1)))
        s.add(AiStep(run_id=uuid.UUID(rid), project_id=uuid.UUID(pid), seq=90, kind="system",
                     output={"approval_id": str(plan_a), "decision": "approved"}))
        await s.commit()
    provider = ScriptedProvider(lambda n, r: finish(n))
    await sweep_once(session_factory, _deps(session_factory, provider, FakeToolbox()), get_settings())
    gone = await _run(session_factory, rid)
    assert gone.state == "stopped" and gone.stop_code == "approval_expired"


async def test_f0201_an_unread_decision_keeps_the_run_alive(client: AsyncClient, session_factory: Factory) -> None:
    pid = await make_project(client)
    rid = await _crashed_run(client, session_factory, pid, "awaiting_approval", PAST)
    aid = await _ask(session_factory, pid, uuid.UUID(rid), kind="C")
    async with session_factory() as s:
        await s.execute(update(AiApproval).where(AiApproval.id == aid).values(state="approved"))
        await s.commit()
    provider = ScriptedProvider(lambda n, r: finish(n))
    await sweep_once(session_factory, _deps(session_factory, provider, FakeToolbox()), get_settings())
    assert (await _run(session_factory, rid)).state == "awaiting_approval"



async def test_f0202_changed_files_baseline_is_this_runs_start(
    client: AsyncClient, session_factory: Factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = uuid.UUID(await make_project(client))
    now = datetime.now(UTC)
    async with session_factory() as s:
        ws = Workspace(project_id=pid, name="d", base_spec_seq=0, spec_seq=0, branch="b", worktree_path=str(tmp_path))
        s.add(ws)
        await s.flush()
        for sha, label, ago in (("a" * 40, "run-start", 60), ("b" * 40, "before-apply", 50), ("c" * 40, "run-start", 5)):
            s.add(WorkspaceCheckpoint(workspace_id=ws.id, project_id=pid, label=label, git_sha=sha, git_tag=f"t{sha[0]}",
                                      spec_seq=0, spec_hash="0" * 64, created_at=now - timedelta(seconds=ago)))
        run = AiRun(project_id=pid, goal="g", started_at=now - timedelta(seconds=10), workspace_id=ws.id)
        s.add(run)
        await s.commit()
        seen: list[tuple[str, ...]] = []

        async def fake_git(path: str, *args: str) -> list[str]:
            seen.append(args)
            return []

        monkeypatch.setattr(wiring, "_git", fake_git)
        await wiring._changed_files(s, ws, run=run)
    diff = next(a for a in seen if a[0] == "diff")
    assert diff[-1] == "c" * 40, seen
