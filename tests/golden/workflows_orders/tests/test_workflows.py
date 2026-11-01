"""Workflow checks (generated): steps run once and in order, a crashed worker resumes after the last recorded
step, a failure undoes completed steps in reverse order, a lost lease cannot overwrite, the API is role-checked
and tenant-scoped. They run against the real database; time is injected or moved in SQL, never slept."""

import datetime as dt
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

import app.hooks.workflows  # noqa: F401  (registers the project's functions once, so the tests can clear them)
from app.db import session_factory
from app.workflows import config, definitions, engine, registry, worker
from app.workflows.models import (
    CANCELLED,
    COMPENSATED,
    COMPENSATION_FAILED,
    FAILED,
    PENDING,
    RUNNING,
    SUCCEEDED,
    Run,
    StepRecord,
)
from tests._auth_support import outbox, sign_in  # noqa: F401

CANARY = "CANARY-5c2e8a91d7f3b40a-do-not-store"


class Crash(BaseException):
    """Stands for a killed process: it is not an Exception, so the runner cannot record it."""


@pytest.fixture(autouse=True)
def _own_handlers() -> Iterator[None]:
    saved = (dict(registry._STEPS), dict(registry._COMPENSATIONS))
    registry.clear_handlers()
    yield
    registry.clear_handlers()
    registry._STEPS.update(saved[0])
    registry._COMPENSATIONS.update(saved[1])


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _run(run_id: uuid.UUID) -> Run:
    async with session_factory() as session:
        return (await session.execute(sa.select(Run).where(Run.id == run_id))).scalar_one()


async def _records(run_id: uuid.UUID) -> list[StepRecord]:
    async with session_factory() as session:
        rows = await session.execute(sa.select(StepRecord).where(StepRecord.run_id == run_id).order_by(StepRecord.finished_at))
        return list(rows.scalars())


async def _sql(statement: str, **params: object) -> None:
    async with session_factory() as session:
        await session.execute(sa.text(statement), params)
        await session.commit()


async def _due(run_id: uuid.UUID) -> None:
    await _sql("UPDATE wf_runs SET next_run_at = now() - interval '1 second' WHERE id = :id", id=run_id)


async def _expire_lease(run_id: uuid.UUID) -> None:
    await _sql("UPDATE wf_runs SET lease_expires_at = now() - interval '1 second' WHERE id = :id", id=run_id)


async def _pump(run_id: uuid.UUID, rounds: int = 60) -> Run:
    """Drive the run like a worker would, moving a retry's due time to now each round."""
    for _ in range(rounds):
        await _due(run_id)
        claimed = await engine.claim(session_factory, "test-worker")
        if claimed is None:
            break
        await engine.drive(session_factory, claimed)
    return await _run(run_id)


async def _claim(who: str = "test-worker") -> engine.Claimed:
    claimed = await engine.claim(session_factory, who)
    assert claimed is not None
    return claimed


def _fast_retry(monkeypatch: pytest.MonkeyPatch, wf: str, attempts: int = 1) -> None:
    for s in definitions.WORKFLOWS[wf]["steps"]:
        monkeypatch.setitem(s, "retry", {"max_attempts": attempts, "backoff_seconds": 1, "backoff": "fixed"})


def test_every_workflow_names_roles_steps_and_a_known_failure_policy() -> None:
    assert definitions.RUNTIME == "postgres"
    for name, wf in definitions.WORKFLOWS.items():
        assert wf["roles"] and wf["steps"], name
        assert wf["on_failure"] in ("compensate", "fail"), name
        assert len({s["name"] for s in wf["steps"]}) == len(wf["steps"]), name
        for s in wf["steps"]:
            assert s["kind"] in ("hook", "job") and s["retry"]["max_attempts"] >= 1, (name, s["name"])


def test_the_runner_refuses_to_start_while_a_declared_function_is_missing() -> None:
    with pytest.raises(RuntimeError):
        registry.load_handlers()


def test_the_backoff_follows_the_declared_shape_up_to_a_cap() -> None:
    fixed = {"backoff_seconds": 7, "backoff": "fixed"}
    expo = {"backoff_seconds": 2, "backoff": "exponential"}
    assert [engine.backoff_delay(fixed, n) for n in (1, 2, 5)] == [7, 7, 7]
    assert [engine.backoff_delay(expo, n) for n in (1, 2, 3)] == [2, 4, 8]
    assert engine.backoff_delay(expo, 60) == config.BACKOFF_CAP_SECONDS


async def test_an_unknown_workflow_and_a_bad_input_are_refused() -> None:
    with pytest.raises(engine.UnknownWorkflow):
        await engine.start("nope", {})
    first = next(iter(definitions.WORKFLOWS))
    with pytest.raises(ValueError):
        await engine.start(first, {"blob": "x" * (config.MAX_INPUT_BYTES + 1)})
    with pytest.raises(ValueError):
        await engine.start(first, {"n": float("nan")})
    with pytest.raises(ValueError):
        await engine.start(first, {}, dedupe_key="")

WF = "order_flow"
STEPS = definitions.WORKFLOWS[WF]["steps"]
NAMES = [s["name"] for s in STEPS]


class Calls:
    """Installs recording functions for every step of WF and every undo (compensate is forced on for all)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.log: list[tuple[str, str, int]] = []
        self.keys: dict[str, set[str]] = {}
        self.fail: dict[str, int] = {}
        self.fail_undo: set[str] = set()
        self.crash_on: str | None = None
        self.before: dict[str, Any] = {}
        for s in STEPS:
            monkeypatch.setitem(s, "compensate", True)
            registry._STEPS[(WF, s["name"])] = self._step(s["name"])
            registry._COMPENSATIONS[(WF, s["name"])] = self._undo(s["name"])

    def _step(self, name: str) -> Any:
        async def fn(ctx: registry.StepContext) -> dict[str, object]:
            self.log.append(("do", name, ctx.attempt))
            self.keys.setdefault(name, set()).add(ctx.idempotency_key)
            if name in self.before:
                await self.before[name](ctx)
            if self.crash_on == name and ctx.attempt == 1:
                raise Crash
            if self.fail.get(name, 0) > 0:
                self.fail[name] -= 1
                raise RuntimeError(f"boom {CANARY}")
            return {"done": name, "seen": sorted(ctx.results)}

        return fn

    def _undo(self, name: str) -> Any:
        async def fn(ctx: registry.StepContext) -> None:
            self.log.append(("undo", name, ctx.attempt))
            assert ctx.compensating and ctx.result == {"done": name, "seen": NAMES[: NAMES.index(name)]}
            if name in self.fail_undo:
                raise RuntimeError("cannot undo")

        return fn

    def did(self, kind: str) -> list[str]:
        return [n for k, n, _ in self.log if k == kind]


async def _start(**kw: Any) -> uuid.UUID:
    return await engine.start(WF, {"order": "o-1"}, **kw)


async def test_the_steps_run_once_each_in_order_and_see_earlier_results(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls(monkeypatch)
    run = await _pump(await _start())
    assert run.status == SUCCEEDED and run.finished_at is not None and run.lease_token is None
    assert calls.did("do") == NAMES and calls.did("undo") == []
    records = await _records(run.id)
    assert [r.step for r in records] == NAMES and {r.status for r in records} == {"succeeded"}
    assert {r.idempotency_key for r in records} == {f"{WF}:{run.id}:{n}" for n in NAMES}


async def test_a_failing_step_is_retried_with_a_durable_backoff_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls(monkeypatch)
    _fast_retry(monkeypatch, WF, attempts=3)
    calls.fail[NAMES[0]] = 1
    run_id = await _start()
    claimed = await _claim()
    assert await engine.drive(session_factory, claimed) == "released"
    waiting = await _run(run_id)
    assert waiting.status == RUNNING and waiting.lease_token is None and waiting.next_run_at > _now()
    assert waiting.error == "RuntimeError" and waiting.attempt == 1
    assert await engine.claim(session_factory, "early") is None  # not due yet
    run = await _pump(run_id)
    assert run.status == SUCCEEDED
    assert calls.log[:2] == [("do", NAMES[0], 1), ("do", NAMES[0], 2)]
    assert len(calls.keys[NAMES[0]]) == 1  # one key for every attempt of the step


async def test_a_failure_for_good_undoes_completed_steps_in_reverse_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls(monkeypatch)
    _fast_retry(monkeypatch, WF)
    monkeypatch.setitem(definitions.WORKFLOWS[WF], "on_failure", "compensate")
    calls.fail[NAMES[-1]] = 99
    run = await _pump(await _start())
    assert run.status == COMPENSATED and run.failed_step == NAMES[-1] and run.error == "RuntimeError"
    assert calls.did("undo") == list(reversed(NAMES[:-1]))  # the failed step itself is not undone
    assert calls.did("do").count(NAMES[-1]) == 1


async def test_on_failure_fail_stops_and_leaves_the_completed_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls(monkeypatch)
    _fast_retry(monkeypatch, WF)
    monkeypatch.setitem(definitions.WORKFLOWS[WF], "on_failure", "fail")
    calls.fail[NAMES[-1]] = 99
    run = await _pump(await _start())
    assert run.status == FAILED and run.failed_step == NAMES[-1]
    assert calls.did("undo") == []


async def test_an_undo_that_keeps_failing_is_visible_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls(monkeypatch)
    _fast_retry(monkeypatch, WF)
    monkeypatch.setitem(definitions.WORKFLOWS[WF], "on_failure", "compensate")
    calls.fail[NAMES[-1]] = 99
    calls.fail_undo.add(NAMES[-2])
    run = await _pump(await _start())
    assert run.status == COMPENSATION_FAILED and run.failed_step == NAMES[-2] and run.finished_at is not None


async def test_a_crashed_worker_resumes_after_the_last_recorded_step(monkeypatch: pytest.MonkeyPatch) -> None:
    if len(NAMES) < 2:
        pytest.skip("needs two steps")
    calls = Calls(monkeypatch)
    calls.crash_on = NAMES[1]
    run_id = await _start()
    with pytest.raises(Crash):
        await engine.drive(session_factory, await _claim("worker-a"))
    stuck = await _run(run_id)
    assert stuck.cursor == 1 and stuck.attempt == 1 and stuck.lease_token is not None
    assert await engine.claim(session_factory, "worker-b") is None  # the lease is still held
    await _expire_lease(run_id)  # the dead worker's lease runs out
    run = await _pump(run_id)
    assert run.status == SUCCEEDED
    assert calls.did("do").count(NAMES[0]) == 1  # a recorded step is never run again
    assert [a for k, n, a in calls.log if n == NAMES[1]] == [1, 2]  # the step in flight ran again, as attempt 2
    assert len({k for ks in calls.keys.values() for k in ks}) == len(NAMES)
    assert [r.step for r in await _records(run_id)] == NAMES


async def test_a_step_that_kills_the_worker_every_time_is_abandoned_not_run_for_ever(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls(monkeypatch)
    _fast_retry(monkeypatch, WF, attempts=2)
    monkeypatch.setitem(definitions.WORKFLOWS[WF], "on_failure", "fail")

    async def die(ctx: registry.StepContext) -> None:
        raise Crash

    calls.before[NAMES[0]] = die
    run_id = await _start()
    for _ in range(2):
        with pytest.raises(Crash):
            await engine.drive(session_factory, await _claim())
        await _expire_lease(run_id)
    run = await _pump(run_id)
    assert run.status == FAILED and run.error == "Abandoned" and calls.did("do") == [NAMES[0]] * 2


async def test_a_worker_that_lost_its_lease_cannot_overwrite_the_new_holder(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls(monkeypatch)
    run_id = await _start()
    stale = await _claim("slow-worker")
    await _expire_lease(run_id)
    fresh = await _claim("fast-worker")
    assert fresh.lease_token != stale.lease_token
    assert await engine.drive(session_factory, stale) == "lost"
    assert calls.log == []  # the stale worker did not even start a step
    assert await engine.drive(session_factory, fresh) == "finished"
    assert (await _run(run_id)).status == SUCCEEDED


async def test_two_workers_never_drive_the_same_run(monkeypatch: pytest.MonkeyPatch) -> None:
    Calls(monkeypatch)
    await _start()
    assert await engine.claim(session_factory, "a") is not None
    assert await engine.claim(session_factory, "b") is None


async def test_cancelling_a_run_that_has_not_started_stops_it_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls(monkeypatch)
    run_id = await _start()
    async with session_factory() as session:
        row = await engine.cancel(session, run_id, None)
        await session.commit()
    assert row is not None and row.status == CANCELLED
    assert await engine.claim(session_factory, "w") is None and calls.log == []


async def test_cancelling_a_running_run_undoes_what_it_did_then_ends_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    if len(NAMES) < 2:
        pytest.skip("needs two steps")
    calls = Calls(monkeypatch)
    monkeypatch.setitem(definitions.WORKFLOWS[WF], "on_failure", "compensate")
    run_id = await _start()

    async def cancel_now(ctx: registry.StepContext) -> None:
        async with session_factory() as session:
            await engine.cancel(session, run_id, None)
            await session.commit()

    calls.before[NAMES[0]] = cancel_now
    run = await _pump(run_id)
    assert run.status == CANCELLED and run.cancel_requested
    assert calls.did("do") == [NAMES[0]] and calls.did("undo") == [NAMES[0]]


async def test_a_run_past_its_deadline_fails_by_the_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls(monkeypatch)
    monkeypatch.setitem(definitions.WORKFLOWS[WF], "on_failure", "fail")
    run_id = await _start()
    await _sql("UPDATE wf_runs SET deadline_at = now() - interval '1 second' WHERE id = :id", id=run_id)
    run = await _pump(run_id)
    assert run.status == FAILED and run.error == "WorkflowTimeout" and calls.log == []


async def test_a_failure_stores_the_error_class_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls(monkeypatch)
    _fast_retry(monkeypatch, WF)
    calls.fail[NAMES[0]] = 99
    run = await _pump(await _start())
    assert run.error == "RuntimeError"
    async with session_factory() as session:
        dump = (await session.execute(sa.text("SELECT row_to_json(r)::text FROM wf_runs r"))).scalars().all()
        dump += (await session.execute(sa.text("SELECT row_to_json(s)::text FROM wf_steps s"))).scalars().all()
    assert CANARY not in "\n".join(dump)


async def test_a_start_with_the_same_dedupe_key_returns_the_same_run(monkeypatch: pytest.MonkeyPatch) -> None:
    Calls(monkeypatch)
    first = await _start(dedupe_key="order-1")
    assert await _start(dedupe_key="order-1") == first
    assert await _start(dedupe_key="order-2") != first
    async with session_factory() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(Run))).scalar_one() == 2


async def test_a_start_joins_the_callers_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    Calls(monkeypatch)
    async with session_factory() as session:
        await engine.start(WF, {}, session=session)
        await session.rollback()
    async with session_factory() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(Run))).scalar_one() == 0


async def test_the_worker_drains_what_is_due(monkeypatch: pytest.MonkeyPatch) -> None:
    Calls(monkeypatch)
    ids = [await _start() for _ in range(3)]
    assert await worker.drain(session_factory, "w") == 3
    assert [(await _run(i)).status for i in ids] == [SUCCEEDED] * 3


async def test_the_api_starts_inspects_and_cancels_a_run_for_a_permitted_role(
    client: AsyncClient, outbox, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001, F811
) -> None:
    Calls(monkeypatch)
    allowed = await sign_in(client, "wf-admin@example.com", roles=["admin"])
    started = await client.post(f"/workflows/{WF}/runs", json={"input": {"order": "o-9"}, "idempotency_key": "k-1"}, headers=allowed)
    assert started.status_code == 202, started.text
    body = started.json()
    assert body["status"] == PENDING and "input" not in body
    again = await client.post(f"/workflows/{WF}/runs", json={"input": {}, "idempotency_key": "k-1"}, headers=allowed)
    assert again.json()["id"] == body["id"]
    run_id = uuid.UUID(body["id"])
    await _pump(run_id)
    detail = (await client.get(f"/workflows/runs/{run_id}", headers=allowed)).json()
    assert detail["status"] == SUCCEEDED and [s["step"] for s in detail["steps"]] == NAMES
    assert "result" not in detail["steps"][0] and "input" not in detail
    listed = (await client.get("/workflows/runs", params={"workflow": WF, "status": SUCCEEDED}, headers=allowed)).json()
    assert [r["id"] for r in listed] == [body["id"]]
    other = (await client.post(f"/workflows/{WF}/runs", json={"input": {}}, headers=allowed)).json()
    cancelled = await client.post(f"/workflows/runs/{other['id']}/cancel", headers=allowed)
    assert cancelled.status_code == 202 and cancelled.json()["status"] == CANCELLED


async def test_the_api_is_default_deny(client: AsyncClient, outbox, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001, F811
    Calls(monkeypatch)
    assert (await client.post(f"/workflows/{WF}/runs", json={})).status_code == 401
    assert (await client.get("/workflows/runs")).status_code == 401
    owner = await sign_in(client, "wf-owner@example.com", roles=["admin"])
    run = (await client.post(f"/workflows/{WF}/runs", json={}, headers=owner)).json()
    outsider = await sign_in(client, "wf-outsider@example.com", roles=[])
    assert (await client.post(f"/workflows/{WF}/runs", json={}, headers=outsider)).status_code == 403
    assert (await client.get(f"/workflows/runs/{run['id']}", headers=outsider)).status_code in (403, 404)
    assert (await client.get("/workflows/runs", headers=outsider)).json() == []
    assert (await client.post(f"/workflows/runs/{run['id']}/cancel", headers=outsider)).status_code in (403, 404)
    assert (await client.post("/workflows/nope/runs", json={}, headers=owner)).status_code == 404
    assert (await client.post(f"/workflows/{WF}/runs", json={"input": {}, "extra": 1}, headers=owner)).status_code == 422
    assert (await client.post(f"/workflows/{WF}/runs", json={"input": {"b": "x" * (config.MAX_INPUT_BYTES + 1)}}, headers=owner)).status_code == 422


async def test_a_tenant_never_sees_starts_or_cancels_another_tenants_runs(
    client: AsyncClient, outbox, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001, F811
) -> None:
    Calls(monkeypatch)
    first = await sign_in(client, "wf-first@example.com", roles=["admin"])
    second = await sign_in(client, "wf-second@example.com", roles=["admin"])
    mine = (await client.post(f"/workflows/{WF}/runs", json={}, headers=first)).json()
    assert (await client.get("/workflows/runs", headers=second)).json() == []
    assert (await client.get(f"/workflows/runs/{mine['id']}", headers=second)).status_code == 404
    assert (await client.post(f"/workflows/runs/{mine['id']}/cancel", headers=second)).status_code == 404
    assert (await _run(uuid.UUID(mine["id"]))).status == PENDING  # untouched
    # the same dedupe key in two tenants makes two runs
    a = (await client.post(f"/workflows/{WF}/runs", json={"idempotency_key": "same"}, headers=first)).json()
    b = (await client.post(f"/workflows/{WF}/runs", json={"idempotency_key": "same"}, headers=second)).json()
    assert a["id"] != b["id"]
    assert len((await client.get("/workflows/runs", headers=second)).json()) == 1


async def test_a_job_step_enqueues_its_job_once_with_the_steps_key(monkeypatch: pytest.MonkeyPatch) -> None:
    WFJ = "receipt_flow"
    for s in definitions.WORKFLOWS[WFJ]["steps"]:
        if s["kind"] == "hook":
            async def noop(ctx: registry.StepContext) -> None:
                return None

            registry._STEPS[(WFJ, s["name"])] = noop
    run_id = await engine.start(WFJ, {"order": "o-1"})
    run = await _pump(run_id)
    assert run.status == SUCCEEDED
    async with session_factory() as session:
        rows = (await session.execute(sa.text("SELECT name, dedupe_key FROM jb_jobs"))).all()
    assert rows == [("send_receipt_email", f"{WFJ}:{run_id}:email")]
    # driving the same recorded run again enqueues nothing more
    assert await engine.claim(session_factory, "w") is None
