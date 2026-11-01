"""Scenario tests for the generated `workflows_orders` project. Copied into the project's tests/ folder by
tests/e2e/test_workflows_stack.py and run against a real Postgres, with real worker processes.

Rules under test: a 3-step saga survives a worker killed with SIGKILL in the middle of a step (the lease runs out,
another worker resumes AFTER the last recorded step: the recorded step is never run again, the step in flight runs
again once, every step ends recorded once); a failing last step undoes the earlier steps in reverse order; a worker
killed in the middle of an undo resumes the undo; two workers share many runs and run every step once.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.db import session_factory
from app.workflows import engine
from app.workflows.models import COMPENSATED, SUCCEEDED, Run, StepRecord

ROOT = Path(__file__).resolve().parent.parent
FLOW = "order_flow"
STEPS = ["reserve_stock", "charge_card", "send_receipt"]


@pytest.fixture
def sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "sink.jsonl"
    monkeypatch.setenv("WF_SINK", str(path))
    return path


@pytest.fixture
def procs() -> Iterator[list[subprocess.Popen[str]]]:
    started: list[subprocess.Popen[str]] = []
    yield started
    for process in started:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=30)


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def events(path: Path, kind: str, step: str | None = None, run_id: uuid.UUID | None = None) -> list[dict]:
    return [
        d for d in lines(path)
        if d["kind"] == kind and (step is None or d["step"] == step) and (run_id is None or d["run"] == str(run_id))
    ]


def start_worker(procs: list, **extra: str) -> subprocess.Popen[str]:  # noqa: ANN001
    env = {**os.environ, "WORKFLOWS_POLL_INTERVAL_SECONDS": "0.05", "WORKFLOWS_LEASE_GRACE_SECONDS": "1", **extra}
    process = subprocess.Popen(
        [sys.executable, "-m", "app.workflows.worker"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    procs.append(process)
    return process


async def wait_for(condition: Callable[[], object], timeout: float = 40.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if (await result) if asyncio.iscoroutine(result) else result:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


async def row(run_id: uuid.UUID) -> Run:
    async with session_factory() as session:
        return (await session.execute(sa.select(Run).where(Run.id == run_id))).scalar_one()


async def records(run_id: uuid.UUID) -> list[tuple[str, str, str, int]]:
    async with session_factory() as session:
        found = await session.execute(sa.select(StepRecord).where(StepRecord.run_id == run_id).order_by(StepRecord.finished_at))
        return [(r.step, r.phase, r.status, r.attempts) for r in found.scalars()]


async def finished(run_id: uuid.UUID, status: str) -> bool:
    return (await row(run_id)).status == status


async def test_a_three_step_saga_survives_a_worker_killed_mid_run(sink, procs) -> None:  # noqa: ANN001
    run_id = await engine.start(FLOW, {"order": "o-1"})
    victim = start_worker(procs, WF_HANG_STEP="charge_card")
    await wait_for(lambda: events(sink, "start", "charge_card"))  # step 1 is recorded, step 2 is in flight
    assert [r[0] for r in await records(run_id)] == ["reserve_stock"]
    victim.send_signal(signal.SIGKILL)
    victim.wait(timeout=30)
    interrupted = await row(run_id)
    assert interrupted.status == "running" and interrupted.cursor == 1 and interrupted.lease_token is not None
    start_worker(procs)  # a healthy worker; the lease (step timeout 2 s + 1 s) runs out, then it resumes
    await wait_for(lambda: finished(run_id, SUCCEEDED))
    await asyncio.sleep(1.0)  # a duplicate would show up late
    assert len(events(sink, "done", "reserve_stock", run_id)) == 1
    assert len(events(sink, "start", "reserve_stock", run_id)) == 1  # the recorded step never ran again
    assert [d["attempt"] for d in events(sink, "start", "charge_card", run_id)] == [1, 2]  # in flight: ran again
    assert len(events(sink, "done", "charge_card", run_id)) == 1 and len(events(sink, "done", "send_receipt", run_id)) == 1
    keys = {d["key"] for d in events(sink, "start", "charge_card", run_id)}
    assert keys == {f"{FLOW}:{run_id}:charge_card"}  # the same idempotency key on both deliveries
    assert [r[0] for r in await records(run_id)] == STEPS
    assert {r[2] for r in await records(run_id)} == {"succeeded"}
    assert events(sink, "undo", None, run_id) == []


async def test_a_failing_last_step_undoes_the_earlier_steps_in_reverse_order(sink, procs) -> None:  # noqa: ANN001
    run_id = await engine.start(FLOW, {"order": "o-2", "fail_at": "send_receipt"})
    start_worker(procs)
    await wait_for(lambda: finished(run_id, COMPENSATED))
    final = await row(run_id)
    assert final.failed_step == "send_receipt" and final.error == "RuntimeError"
    assert [d["attempt"] for d in events(sink, "start", "send_receipt", run_id)] == [1, 2, 3]  # the step's retry cap
    assert [d["step"] for d in events(sink, "undo", None, run_id)] == ["charge_card", "reserve_stock"]


async def test_a_worker_killed_mid_undo_resumes_the_undo_without_repeating_a_finished_one(sink, procs) -> None:  # noqa: ANN001
    run_id = await engine.start(FLOW, {"order": "o-3", "fail_at": "send_receipt"})
    victim = start_worker(procs, WF_HANG_UNDO="charge_card")
    await wait_for(lambda: events(sink, "undo_start", "charge_card", run_id))
    victim.send_signal(signal.SIGKILL)
    victim.wait(timeout=30)
    assert (await row(run_id)).status == "compensating"
    start_worker(procs)
    await wait_for(lambda: finished(run_id, COMPENSATED))
    await asyncio.sleep(1.0)
    assert [d["step"] for d in events(sink, "undo", None, run_id)] == ["charge_card", "reserve_stock"]
    assert len(events(sink, "undo_start", "reserve_stock", run_id)) == 1
    assert [d["attempt"] for d in events(sink, "undo_start", "charge_card", run_id)] == [1, 2]


async def test_two_worker_processes_run_every_step_of_every_run_exactly_once(sink, procs) -> None:  # noqa: ANN001
    ids = [await engine.start(FLOW, {"order": f"o-{i}", "sleep": 0.05}) for i in range(10)]
    first, second = start_worker(procs), start_worker(procs)
    for run_id in ids:
        await wait_for(lambda run_id=run_id: finished(run_id, SUCCEEDED))
    await asyncio.sleep(1.0)
    done = events(sink, "done")
    assert len(done) == 30 and len({(d["run"], d["step"]) for d in done}) == 30
    assert len({d["pid"] for d in done}) == 2  # both processes really shared the work
    for process in (first, second):
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=30) == 0
