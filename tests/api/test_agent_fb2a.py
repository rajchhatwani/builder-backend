"""FB2a: agent-loop correctness: lease/takeover, atomic approvals + apply, live-run guard,
crash-resume sweeper, run-wide budgets, expired approvals, automatic checkpoints."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.exceptions import AppError
from app.models.agent import AiApproval, AiDraftOp, AiRun, AiStep
from app.models.project import Project
from app.models.workspace import Workspace
from app.services.agent import run_service
from app.services.agent.draft import apply_draft
from app.services.agent.run_service import AgentDeps, RunDriver
from app.services.agent.sweeper import sweep_once
from app.services.ai.base import Completion, CompletionRequest, ModelProvider
from app.services.ai.gateway import ModelGateway
from app.services.spec_service import SpecService
from tests.api._approval_hash import reviewer_sends_hash  # noqa: F401  (isort: skip)
from tests.api._auth_helpers import make_project
from tests.api.test_agent_e2e import (  # noqa: F401  (fixtures + helpers for the real-workspace test)
    PLAN,
    Script,
    _capture_factory,
    _cleanup,
    _decide,
    _resume,
    _setup,
    ws_settings,
)
from tests.api.test_agent_e2e import call as ecall
from tests.api.test_agent_e2e import install as e2e_install
from tests.api.test_agent_runs import (  # noqa: F401
    FakeApprovals,
    FakeGates,
    FakeToolbox,
    Factory,
    ScriptedProvider,
    _new,
    _patch_run,
    _run,
    _steps,
    _url,
    finish,
    install,
)

PAST = timedelta(seconds=-5)


class BlockingProvider(ModelProvider):
    """Enters, tells the test, then waits until released; then answers or fails as told."""

    name = "blocking"

    def __init__(self, answer: Completion | Exception, hold: float | None = None) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.answer, self.hold = answer, hold

    async def complete(self, model: str, request: CompletionRequest) -> Completion:
        self.entered.set()
        if self.hold is not None:
            await asyncio.sleep(self.hold)
        else:
            await self.release.wait()
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def stream(self, model: str, request: CompletionRequest) -> Any:
        raise NotImplementedError


async def _driver(factory: Factory, pid: str, provider: ModelProvider, owner: str, **kw: Any) -> tuple[RunDriver, Any]:
    s = factory()
    sess = await s.__aenter__()
    project = await sess.get(Project, uuid.UUID(pid))
    assert project is not None
    settings = get_settings()
    toolbox = FakeToolbox()
    driver = RunDriver(
        sess, settings, toolbox, FakeApprovals(factory), ModelGateway(sess, settings, lambda key: provider),
        org_id=project.organization_id, owner=owner, gates=FakeGates(), **kw,
    )  # fmt: skip
    return driver, s


async def _draft_op(factory: Factory, rid: str, pid: str, seq: int = 1, **payload: Any) -> None:
    async with factory() as s:
        s.add(AiDraftOp(run_id=uuid.UUID(rid), project_id=uuid.UUID(pid), seq=seq, op_type="add_entity",
                        payload=payload or {"entity": {"name": "Invoice"}}))  # fmt: skip
        await s.commit()


async def _draft_ops(factory: Factory, rid: str) -> int:
    async with factory() as s:
        q = select(func.count()).select_from(AiDraftOp).where(AiDraftOp.run_id == uuid.UUID(rid))
        return int((await s.execute(q)).scalar_one())


# -- S1-001 ---------------------------------------------------------------------------------------


async def test_takeover_driver_that_fails_does_not_destroy_the_draft(
    client: AsyncClient, session_factory: Factory
) -> None:
    pid = await make_project(client)
    rid = await _new(client, pid)
    await _patch_run(session_factory, rid, state="running", phase="build")
    await _draft_op(session_factory, rid, pid)
    provider = BlockingProvider(RuntimeError("boom after takeover"))
    driver, cm = await _driver(session_factory, pid, provider, "driver-a")
    task = asyncio.create_task(driver.drive(uuid.UUID(rid)))
    await asyncio.wait_for(provider.entered.wait(), 10)
    # the lease was taken over by driver B (A looked dead to B)
    await _patch_run(session_factory, rid, lease_owner="driver-b", lease_until=datetime.now(UTC) + timedelta(seconds=60))
    provider.release.set()
    try:
        await asyncio.wait_for(task, 10)  # A aborts safely: no raise, no cleanup
    finally:
        await cm.__aexit__(None, None, None)
    run = await _run(session_factory, rid)
    assert run.state == "running" and run.lease_owner == "driver-b"  # B's run, untouched
    assert await _draft_ops(session_factory, rid) == 1  # B's draft is intact
    assert not [s for s in await _steps(session_factory, rid) if s.kind == "model"]  # A wrote nothing


async def test_heartbeat_keeps_the_lease_during_a_slow_model_call(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_service, "LEASE_SECONDS", 0.6)
    pid = await make_project(client)
    rid = await _new(client, pid)
    provider = BlockingProvider(finish(1), hold=1.6)  # the call outlives the lease 2.5 times
    a, cm_a = await _driver(session_factory, pid, provider, "driver-a")
    task = asyncio.create_task(a.drive(uuid.UUID(rid)))
    await asyncio.wait_for(provider.entered.wait(), 10)
    await asyncio.sleep(1.0)  # lease would have expired at 0.6 s without the heartbeat
    b, cm_b = await _driver(session_factory, pid, provider, "driver-b")
    try:
        with pytest.raises(AppError) as exc:
            await b._acquire(uuid.UUID(rid))
        assert exc.value.code == "run_leased"
        await asyncio.wait_for(task, 15)
    finally:
        await cm_a.__aexit__(None, None, None)
        await cm_b.__aexit__(None, None, None)
    assert (await _run(session_factory, rid)).state == "awaiting_approval"  # A finished the turn


# -- S1-003 ---------------------------------------------------------------------------------------


class Crash(BaseException):
    """A process death: not an Exception, so no handler of the driver turns it into 'failed'."""


async def test_consumed_marker_and_state_move_are_one_transaction(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await make_project(client)
    rid = await _new(client, pid)
    await _patch_run(session_factory, rid, state="awaiting_approval", phase="plan")
    async with session_factory() as s:
        s.add(AiApproval(run_id=uuid.UUID(rid), project_id=uuid.UUID(pid), kind="A", subject="plan",
                         payload={"plan": {"entities": ["Invoice"]}}, state="approved",
                         bound_spec_hash="0" * 64, expires_at=datetime.now(UTC) + timedelta(days=1)))  # fmt: skip
        await s.commit()
    real = SpecService.assemble
    calls = {"n": 0}

    async def dying(self: SpecService, project_id: uuid.UUID) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise Crash()
        return await real(self, project_id)

    monkeypatch.setattr(SpecService, "assemble", dying)
    driver, cm = await _driver(session_factory, pid, ScriptedProvider(lambda n, r: finish(n)), "driver-a")
    try:
        with pytest.raises(Crash):
            await driver.drive(uuid.UUID(rid))  # dies after the marker, before the plan is stored
    finally:
        await cm.__aexit__(None, None, None)
    assert not [s for s in await _steps(session_factory, rid) if s.kind == "system"]  # marker rolled back
    run = await _run(session_factory, rid)
    assert run.state == "awaiting_approval" and run.plan is None
    install_provider = ScriptedProvider(lambda n, r: finish(n))
    d2, cm2 = await _driver(session_factory, pid, install_provider, "driver-b")
    try:
        await d2.drive(uuid.UUID(rid))  # old code: 409 nothing_to_resume forever
    finally:
        await cm2.__aexit__(None, None, None)
    run = await _run(session_factory, rid)
    assert run.phase == "build" and run.plan and run.plan["entities"] == ["Invoice"]


# -- S1-005 ---------------------------------------------------------------------------------------


async def _applying_run(client: AsyncClient, factory: Factory, owner: str) -> tuple[str, str]:
    pid = await make_project(client)
    rid = await _new(client, pid)
    async with factory() as s:
        base = await SpecService(s).assemble(uuid.UUID(pid))
        from app.services.agent.draft import spec_seq

        plan = {"base_spec": base.model_dump(mode="json"), "base_spec_seq": await spec_seq(s, uuid.UUID(pid))}
    await _patch_run(factory, rid, state="applying", phase="apply", plan=plan,
                     lease_owner=owner, lease_until=datetime.now(UTC) + timedelta(seconds=60))  # fmt: skip
    await _draft_op(factory, rid, pid)
    return pid, rid


async def _entities(factory: Factory, pid: str) -> list[str]:
    async with factory() as s:
        return [e.name for e in (await SpecService(s).assemble(uuid.UUID(pid))).entities]


async def test_apply_commits_spec_state_and_draft_removal_together_and_is_idempotent(
    client: AsyncClient, session_factory: Factory
) -> None:
    pid, rid = await _applying_run(client, session_factory, "driver-a")
    async with session_factory() as s:
        out = await apply_draft(s, uuid.UUID(rid), owner="driver-a")
    assert out.status == "applied"
    # a crash right here (before the driver does anything else) leaves a consistent run
    run = await _run(session_factory, rid)
    assert run.state == "applied" and run.lease_owner is None
    assert await _draft_ops(session_factory, rid) == 0
    assert await _entities(session_factory, pid) == ["Invoice"]
    async with session_factory() as s:
        again = await apply_draft(s, uuid.UUID(rid), owner="driver-a")  # re-run after the crash
    assert again.status == "applied"
    assert await _entities(session_factory, pid) == ["Invoice"]  # not applied twice
    async with session_factory() as s:
        n = (await s.execute(select(func.count()).select_from(AiStep).where(
            AiStep.run_id == uuid.UUID(rid), AiStep.kind == "system"))).scalar_one()
    assert n == 1  # one "applied" step


async def test_apply_by_a_driver_that_lost_the_lease_writes_nothing(
    client: AsyncClient, session_factory: Factory
) -> None:
    pid, rid = await _applying_run(client, session_factory, "driver-b")
    async with session_factory() as s:
        out = await apply_draft(s, uuid.UUID(rid), owner="driver-a")  # A lost the lease to B
    assert out.status == "conflict"
    assert await _entities(session_factory, pid) == []
    run = await _run(session_factory, rid)
    assert run.state == "applying" and await _draft_ops(session_factory, rid) == 1


# -- S1-006 ---------------------------------------------------------------------------------------


async def _workspace(factory: Factory, pid: str, name: str = "w") -> uuid.UUID:
    async with factory() as s:
        ws = Workspace(project_id=uuid.UUID(pid), name=name, base_spec_seq=0, spec_seq=0, branch=f"b-{name}")
        s.add(ws)
        await s.commit()
        return ws.id


async def test_one_live_run_per_workspace_api_and_index(client: AsyncClient, session_factory: Factory) -> None:
    pid = await make_project(client)
    ws = await _workspace(session_factory, pid)
    first = await client.post(f"/projects/{pid}/agent/runs", json={"goal": "one", "workspace_id": str(ws)})
    assert first.status_code == 201, first.text
    second = await client.post(f"/projects/{pid}/agent/runs", json={"goal": "two", "workspace_id": str(ws)})
    assert second.status_code == 409 and second.json()["code"] == "workspace_busy"
    # the index holds even when the service check is bypassed
    async with session_factory() as s:
        s.add(AiRun(project_id=uuid.UUID(pid), workspace_id=ws, goal="sneaky", state="created", phase="plan", budgets={}))
        with pytest.raises(IntegrityError):
            await s.commit()
    # a finished run frees the workspace
    assert (await client.post(_url(pid, first.json()["id"], "/cancel"))).status_code == 200
    third = await client.post(f"/projects/{pid}/agent/runs", json={"goal": "three", "workspace_id": str(ws)})
    assert third.status_code == 201


async def test_live_runs_per_project_are_capped(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_service, "get_settings", lambda: get_settings().model_copy(update={"agent_max_live_runs_per_project": 2}))
    pid = await make_project(client)
    for _ in range(2):
        assert (await client.post(f"/projects/{pid}/agent/runs", json={"goal": "g"})).status_code == 201
    r = await client.post(f"/projects/{pid}/agent/runs", json={"goal": "g"})
    assert r.status_code == 409 and r.json()["code"] == "too_many_runs"


# -- B-003 ----------------------------------------------------------------------------------------


def _deps(factory: Factory, provider: ModelProvider, toolbox: FakeToolbox) -> AgentDeps:
    return AgentDeps(toolbox=toolbox, approvals=FakeApprovals(factory), gates=FakeGates(),
                     provider_factory=lambda key: provider)  # fmt: skip


async def _crashed_run(client: AsyncClient, factory: Factory, pid: str, state: str, lease: timedelta) -> str:
    rid = await _new(client, pid)
    await _patch_run(factory, rid, state=state, phase="build", lease_owner="dead",
                     lease_until=datetime.now(UTC) + lease)  # fmt: skip
    return rid


async def test_sweeper_redrives_orphans_and_honours_the_lease(
    client: AsyncClient, session_factory: Factory
) -> None:
    pid = await make_project(client)
    orphan = await _crashed_run(client, session_factory, pid, "running", PAST)
    live = await _crashed_run(client, session_factory, pid, "running", timedelta(seconds=30))
    waiting = await _crashed_run(client, session_factory, pid, "awaiting_approval", PAST)
    fresh = await _new(client, pid)  # created, never started
    provider = ScriptedProvider(lambda n, r: finish(n))
    taken = await sweep_once(session_factory, _deps(session_factory, provider, FakeToolbox()),
                             get_settings().model_copy(update={"agent_sweep_max_runs": 10}))  # fmt: skip
    assert taken == [uuid.UUID(orphan)]
    assert (await _run(session_factory, orphan)).state == "awaiting_approval"  # driven to its next pause
    assert any((s.output or {}).get("recovered") for s in await _steps(session_factory, orphan))
    for rid, state in ((live, "running"), (waiting, "awaiting_approval"), (fresh, "created")):
        assert (await _run(session_factory, rid)).state == state
        assert not await _steps(session_factory, rid)
    assert (await _run(session_factory, live)).lease_owner == "dead"


async def test_sweeper_fails_a_run_that_keeps_crashing_its_driver(
    client: AsyncClient, session_factory: Factory
) -> None:
    pid = await make_project(client)
    rid = await _crashed_run(client, session_factory, pid, "running", PAST)
    await _draft_op(session_factory, rid, pid)
    async with session_factory() as s:
        for i in range(3):
            s.add(AiStep(run_id=uuid.UUID(rid), project_id=uuid.UUID(pid), seq=i + 1, kind="system",
                         output={"recovered": True, "attempt": i + 1}))  # fmt: skip
        await s.commit()
    provider = ScriptedProvider(lambda n, r: finish(n))
    await sweep_once(session_factory, _deps(session_factory, provider, FakeToolbox()), get_settings())
    run = await _run(session_factory, rid)
    assert run.state == "failed" and run.stop_code == "crash_loop"
    assert provider.requests == [] and await _draft_ops(session_factory, rid) == 0


# -- B-008 / S1-009 -------------------------------------------------------------------------------


async def test_step_and_wall_budgets_are_run_wide(
    client: AsyncClient, install: Any, session_factory: Factory  # noqa: F811
) -> None:
    provider = ScriptedProvider(lambda n, r: finish(n))
    install(provider)
    pid = await make_project(client)
    steps_run = await _new(client, pid)
    await _patch_run(session_factory, steps_run, state="running", phase="build", steps_used=60)  # used by earlier drives
    r = await client.post(_url(pid, steps_run, "/resume"))
    assert r.json()["state"] == "stopped" and r.json()["stop_code"] == "budget_steps"
    wall_run = await _new(client, pid)
    await _patch_run(session_factory, wall_run, state="running", phase="build", wall_ms_used=901_000)
    r = await client.post(_url(pid, wall_run, "/resume"))
    assert r.json()["state"] == "stopped" and r.json()["stop_code"] == "budget_wall"
    assert provider.requests == []  # neither run was allowed another model call


async def test_wall_time_is_persisted_on_the_run(client: AsyncClient, session_factory: Factory) -> None:
    pid = await make_project(client)
    rid = await _new(client, pid)
    ticks = iter(range(0, 1000, 10))
    provider = ScriptedProvider(lambda n, r: finish(n))
    driver, cm = await _driver(session_factory, pid, provider, "driver-a", clock=lambda: float(next(ticks)))
    try:
        await driver.drive(uuid.UUID(rid))
    finally:
        await cm.__aexit__(None, None, None)
    assert (await _run(session_factory, rid)).wall_ms_used >= 10_000


# -- S1-010 ---------------------------------------------------------------------------------------


async def test_expired_pending_approval_does_not_block_resume(
    client: AsyncClient, install: Any, session_factory: Factory  # noqa: F811
) -> None:
    install(ScriptedProvider(lambda n, r: finish(n)))
    pid = await make_project(client)
    rid = await _new(client, pid)
    await _patch_run(session_factory, rid, state="awaiting_approval", phase="plan")
    async with session_factory() as s:
        row = AiApproval(run_id=uuid.UUID(rid), project_id=uuid.UUID(pid), kind="A", subject="plan",
                         payload={}, bound_spec_hash="0" * 64, expires_at=datetime.now(UTC) - timedelta(hours=1))  # fmt: skip
        s.add(row)
        await s.commit()
        aid = row.id
    r = await client.post(_url(pid, rid, "/resume"))
    assert r.status_code == 200, r.text  # old code: 409 approval_pending forever
    async with session_factory() as s:
        assert (await s.get(AiApproval, aid)).state == "expired"  # type: ignore[union-attr]


# -- B-015 ----------------------------------------------------------------------------------------


async def test_automatic_checkpoints_at_run_start_and_before_apply(client: AsyncClient, ws_settings: Any) -> None:  # noqa: F811
    pid, ws, rid = await _setup(client)
    e2e_install(Script([
        ecall("finish", summary="plan", plan=PLAN),
        ecall("add_entity", entity={"name": "Invoice"}),
        ecall("finish", summary="built"),
        ecall("finish", summary="apply"),
    ]))  # fmt: skip
    await _resume(client, pid, rid)
    await _decide(client, pid)
    await _resume(client, pid, rid)
    await _decide(client, pid)
    run = await _resume(client, pid, rid)
    assert run["state"] == "applied", run
    labels = [c["label"] for c in (await client.get(f"/projects/{pid}/workspaces/{ws}")).json()["checkpoints"]]
    assert "run-start" in labels and "before-apply" in labels
    detail = (await client.get(f"/projects/{pid}/agent/runs/{rid}")).json()
    notes = [s["output"] for s in detail["steps"] if (s["output"] or {}).get("checkpoint")]
    assert [n["checkpoint"] for n in notes] == ["run-start", "before-apply"] and all(n.get("checkpoint_id") for n in notes)


async def test_failed_checkpoint_never_blocks_the_run(
    client: AsyncClient, install: Any, session_factory: Factory  # noqa: F811
) -> None:
    install(ScriptedProvider(lambda n, r: finish(n)))
    pid = await make_project(client)
    ws = await _workspace(session_factory, pid)  # a workspace row without worktree/preview root
    r = await client.post(f"/projects/{pid}/agent/runs", json={"goal": "g", "workspace_id": str(ws)})
    rid = r.json()["id"]
    resumed = await client.post(_url(pid, rid, "/resume"))
    assert resumed.status_code == 200 and resumed.json()["state"] == "awaiting_approval"
    cps = [s.output for s in await _steps(session_factory, rid) if (s.output or {}).get("checkpoint")]
    assert cps and cps[0]["checkpoint"] == "run-start" and cps[0].get("checkpoint_failed")
