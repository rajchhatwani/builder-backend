"""Scenario tests for the generated `jobs_invoices` project. Copied into the project's tests/ folder by
tests/e2e/test_jobs_stack.py and run against a real Postgres, with real worker processes.

Rules under test: with two workers every job runs exactly once; a worker killed with SIGKILL in the middle of
a job loses nothing (the lease runs out, another worker runs the job again, once); a cron tick fires one job
however many schedulers race for it; a job that keeps failing ends dead after its cap (visible with the admin
command, requeue-able) and no secret reaches the stored error; SIGTERM lets the running job finish.
"""

import asyncio
import datetime as dt
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
from app.jobs import cron, definitions, queue, scheduler
from app.jobs.models import DEAD, PENDING, SUCCEEDED, Job

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "sink.jsonl"
    monkeypatch.setenv("JOBS_SINK", str(path))
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


def worker_env(**extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "JOBS_POLL_INTERVAL_SECONDS": "0.05",
        "JOBS_LEASE_GRACE_SECONDS": "1",
        "JOBS_SCHEDULER_TICK_SECONDS": "0.1",
        **extra,
    }


def start_worker(procs: list, group: str = "default", **extra: str) -> subprocess.Popen[str]:  # noqa: ANN001
    process = subprocess.Popen(
        [sys.executable, "-m", "app.jobs.worker", "--group", group],
        cwd=ROOT, env=worker_env(**extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    procs.append(process)
    return process


async def wait_for(condition: Callable[[], object], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if (await result) if asyncio.iscoroutine(result) else result:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


async def row(job_id: uuid.UUID) -> Job:
    async with session_factory() as session:
        return (await session.execute(sa.select(Job).where(Job.id == job_id))).scalar_one()


async def status_of(job_id: uuid.UUID) -> str:
    return (await row(job_id)).status


def done(path: Path, job_id: uuid.UUID | None = None) -> list[dict]:
    return [d for d in lines(path) if d["kind"] == "done" and (job_id is None or d["job_id"] == str(job_id))]


async def test_two_worker_processes_run_every_job_exactly_once(sink, procs) -> None:  # noqa: ANN001
    ids = [await queue.enqueue("send_invoice", {"sleep": 0.05, "n": i}) for i in range(24)]
    assert all(ids)
    first, second = start_worker(procs), start_worker(procs)
    await wait_for(lambda: len(done(sink)) >= 24)
    await asyncio.sleep(1.0)  # a duplicate would show up late
    finished = done(sink)
    assert sorted(d["job_id"] for d in finished) == sorted(str(i) for i in ids)  # once each, none lost
    assert len({d["pid"] for d in finished}) == 2  # both processes really shared the work
    for process in (first, second):
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=30) == 0
    async with session_factory() as session:
        assert (await session.execute(sa.select(sa.func.count()).where(Job.status == SUCCEEDED))).scalar_one() == 24


async def test_a_worker_killed_mid_job_loses_nothing_and_the_job_runs_to_completion_once(sink, procs) -> None:  # noqa: ANN001
    job_id = await queue.enqueue("send_invoice", {"n": 1})
    assert job_id is not None
    victim = start_worker(procs, JOBS_HANG_FIRST="1")
    await wait_for(lambda: [d for d in lines(sink) if d["kind"] == "start"])
    victim.send_signal(signal.SIGKILL)
    victim.wait(timeout=30)
    assert await status_of(job_id) == "running"  # the dead worker still holds the lease
    assert done(sink) == []
    start_worker(procs)  # a healthy worker; the lease (timeout 2 s + 1 s) runs out, then it takes over
    await wait_for(lambda: done(sink, job_id), timeout=40)
    await asyncio.sleep(1.0)
    finished = done(sink, job_id)
    assert len(finished) == 1 and finished[0]["attempt"] == 2  # completed once, on the second delivery
    starts = [d for d in lines(sink) if d["kind"] == "start"]
    assert [d["attempt"] for d in starts] == [1, 2] and starts[0]["pid"] != starts[1]["pid"]
    final = await row(job_id)
    assert (final.status, final.attempts, final.lease_token) == (SUCCEEDED, 2, None)


async def test_a_cron_tick_enqueues_one_job_however_many_schedulers_race(sink, procs) -> None:  # noqa: ANN001
    name = "weekly_dunning_monday"
    cfg = definitions.SCHEDULES[name]
    spec, tz = cron.parse(cfg["cron"]), cron.zone(cfg["timezone"])
    assert cfg["timezone"] == "Asia/Kolkata"
    # Two real worker processes of the "reports" group run their own schedulers (every 0.1 s) all along.
    start_worker(procs, "reports"), start_worker(procs, "reports")
    t0 = dt.datetime.now(dt.UTC)
    await scheduler.fire_due(session_factory, t0)  # first sight of the schedule: baseline only
    tick = cron.next_fire(spec, tz, t0)
    assert tick is not None and tick.astimezone(tz).weekday() == 0 and tick.astimezone(tz).hour == 6
    now = tick + dt.timedelta(seconds=3)
    results = await asyncio.gather(*[scheduler.fire_due(session_factory, now) for _ in range(12)])
    assert sum(len(r) for r in results) == 1
    # fire_due ran with a made-up clock a week ahead, so the job is stamped for then: make it due now
    async with session_factory() as session:
        await session.execute(sa.update(Job).where(Job.name == "weekly_dunning").values(run_at=dt.datetime.now(dt.UTC)))
        await session.commit()
    await wait_for(lambda: [d for d in done(sink) if d["name"] == "weekly_dunning"])
    await asyncio.sleep(1.0)
    ran = [d for d in done(sink) if d["name"] == "weekly_dunning"]
    assert len(ran) == 1 and ran[0]["payload"]["schedule"] == name
    async with session_factory() as session:
        jobs = list((await session.scalars(sa.select(Job).where(Job.name == "weekly_dunning"))).all())
    assert len(jobs) == 1 and jobs[0].status == SUCCEEDED  # the real-clock schedulers never fired a stray tick


async def test_a_job_that_keeps_failing_ends_dead_and_can_be_requeued(sink, procs) -> None:  # noqa: ANN001
    job_id = await queue.enqueue("send_invoice", {"fail": True, "card": "4111111111111111"})
    assert job_id is not None
    start_worker(procs)
    await wait_for(lambda: _is(job_id, DEAD), timeout=60)
    final = await row(job_id)
    assert (final.attempts, final.last_error) == (4, "RuntimeError")  # the cap from the spec; the class only
    assert "hunter2" not in repr(final.last_error)
    starts = [d for d in lines(sink) if d["kind"] == "start"]
    assert [d["attempt"] for d in starts] == [1, 2, 3, 4]
    gaps = [b["t"] - a["t"] for a, b in zip(starts, starts[1:], strict=False)]
    assert gaps[0] >= 0.9 and gaps[1] >= 1.9 and gaps[2] >= 3.9  # 1 s, 2 s, 4 s: exponential backoff
    for process in procs:  # no worker may pick the job up again while the operator looks at it
        process.kill()
        process.wait(timeout=30)
    listed = subprocess.run(
        [sys.executable, "-m", "app.jobs.admin", "list-dead"], cwd=ROOT, env=worker_env(), capture_output=True, text=True, timeout=120
    )
    assert listed.returncode == 0 and str(job_id) in listed.stdout
    assert "4111" not in listed.stdout and "hunter2" not in listed.stdout  # a payload is never printed
    requeued = subprocess.run(
        [sys.executable, "-m", "app.jobs.admin", "requeue", str(job_id)], cwd=ROOT, env=worker_env(), capture_output=True, text=True, timeout=120
    )
    assert requeued.returncode == 0 and "requeued 1" in requeued.stdout
    again = await row(job_id)
    assert (again.status, again.attempts) == (PENDING, 0)


async def _is(job_id: uuid.UUID, status: str) -> bool:
    return await status_of(job_id) == status


async def test_sigterm_lets_the_running_job_finish_then_the_worker_exits(sink, procs) -> None:  # noqa: ANN001
    job_id = await queue.enqueue("send_invoice", {"sleep": 1.2})
    assert job_id is not None
    process = start_worker(procs)
    await wait_for(lambda: [d for d in lines(sink) if d["kind"] == "start"])
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=30) == 0
    assert len(done(sink, job_id)) == 1  # it finished the job it had before leaving
    assert await status_of(job_id) == SUCCEEDED
