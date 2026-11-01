"""Job checks (generated): a job runs once, retries back off to a cap and then die visibly, a lost lease is
re-delivered, schedules fire once. They run against the real database; time is injected, never slept."""

import asyncio
import datetime as dt
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa

import app.hooks.jobs  # noqa: F401  (registers the project's handlers once, so the tests can clear them)
from app.db import session_factory
from app.jobs import config, cron, definitions, queue, registry, scheduler, worker
from app.jobs.models import DEAD, PENDING, RUNNING, SUCCEEDED, Job, ScheduleFire

NAME = "send_invoice"
QUEUE = "default"
MAX_ATTEMPTS = 4
RETRY = definitions.JOBS[NAME]["retry"]


@pytest.fixture(autouse=True)
def _own_handlers() -> Iterator[None]:
    """Each test registers the handlers it needs; the project's own are put back afterwards."""
    saved = dict(registry._HANDLERS)
    registry._HANDLERS.clear()
    yield
    registry._HANDLERS.clear()
    registry._HANDLERS.update(saved)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _row(job_id: uuid.UUID) -> Job:
    async with session_factory() as session:
        return (await session.execute(sa.select(Job).where(Job.id == job_id))).scalar_one()


async def _count(*where: sa.ColumnElement[bool]) -> int:
    async with session_factory() as session:
        return int((await session.execute(sa.select(sa.func.count()).select_from(Job).where(*where))).scalar_one())


async def _add(**kw: object) -> uuid.UUID:
    job_id = await queue.enqueue(NAME, {"n": 1}, **kw)  # type: ignore[arg-type]
    assert job_id is not None
    return job_id


# --- the definitions ---------------------------------------------------------------------------


def test_every_job_queue_has_a_worker_group_and_a_handler_name() -> None:
    served = {q for g in definitions.GROUPS.values() for q in g["queues"]}
    for name, job in definitions.JOBS.items():
        assert job["queue"] in served, name
        assert job["handler"].isidentifier(), name


def test_schedules_use_the_strict_cron_and_name_a_job() -> None:
    for name, sched in definitions.SCHEDULES.items():
        cron.validate(sched["cron"], sched["timezone"])
        assert sched["job"] in definitions.JOBS, name


def test_cron_refuses_what_the_builder_refuses() -> None:
    for bad in ("* * * * * *", "61 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *", "* * * * 7", "@daily", "*/0 * * * *", "MON * * * *"):
        with pytest.raises(cron.CronError):
            cron.parse(bad)


def test_the_retry_delay_follows_the_declared_backoff() -> None:
    delays = [queue.backoff_delay(RETRY, n) for n in range(1, 8)]
    base = float(RETRY["backoff_seconds"])
    if RETRY["backoff"] == "fixed":
        assert set(delays) == {min(base, config.BACKOFF_CAP_SECONDS)}
    else:
        assert delays[0] == base
        assert delays[1] == min(2 * base, config.BACKOFF_CAP_SECONDS)
        assert delays == sorted(delays) and max(delays) <= config.BACKOFF_CAP_SECONDS


def test_handlers_must_match_the_spec() -> None:
    async def nope(ctx: registry.JobContext) -> None: ...

    with pytest.raises(ValueError, match="unknown job"):
        registry.handler("not_a_job")(nope)
    with pytest.raises(ValueError, match="function named"):
        registry.handler(NAME)(nope)


def test_a_declared_job_without_a_handler_stops_the_worker() -> None:
    with pytest.raises(RuntimeError, match="no handler registered"):
        registry.load_handlers()


# --- enqueue -----------------------------------------------------------------------------------


async def test_a_rolled_back_write_enqueues_nothing_and_a_committed_one_does() -> None:
    async with session_factory() as session:
        job_id = await queue.enqueue(NAME, {"n": 1}, session=session)
        assert job_id is not None
        await session.rollback()
    assert await _count() == 0
    async with session_factory() as session:
        job_id = await queue.enqueue(NAME, {"n": 2}, session=session)
        await session.commit()
    assert job_id is not None and (await _row(job_id)).status == PENDING


async def test_the_caller_sees_the_job_only_after_its_own_commit() -> None:
    async with session_factory() as session:
        await queue.enqueue(NAME, {"n": 1}, session=session)
        assert await queue.claim(session_factory, [QUEUE], "w") is None  # not committed: not visible
        await session.commit()
    assert await queue.claim(session_factory, [QUEUE], "w") is not None


async def test_a_dedupe_key_enqueues_once() -> None:
    first = await queue.enqueue(NAME, {}, dedupe_key="once")
    second = await queue.enqueue(NAME, {}, dedupe_key="once")
    assert first is not None and second is None
    assert await _count() == 1


async def test_enqueue_refuses_unknown_jobs_and_non_json_payloads() -> None:
    with pytest.raises(queue.UnknownJob):
        await queue.enqueue("nothing_like_this", {})
    with pytest.raises(ValueError, match="JSON"):
        await queue.enqueue(NAME, {"x": object()})
    with pytest.raises(ValueError, match="at most"):
        await queue.enqueue(NAME, {"x": "y" * (config.MAX_PAYLOAD_BYTES + 1)})
    assert await _count() == 0


async def test_a_job_can_wait_for_its_run_at() -> None:
    t0 = _now()
    job_id = await _add(run_at=t0 + dt.timedelta(minutes=5))
    assert await queue.claim(session_factory, [QUEUE], "w", now=t0) is None
    claimed = await queue.claim(session_factory, [QUEUE], "w", now=t0 + dt.timedelta(minutes=5))
    assert claimed is not None and claimed.id == job_id


# --- exactly once ------------------------------------------------------------------------------


async def test_two_workers_run_every_job_exactly_once() -> None:
    ran: list[uuid.UUID] = []

    async def handle(ctx: registry.JobContext) -> None:
        ran.append(ctx.job_id)
        await asyncio.sleep(0.005)

    handle.__name__ = definitions.JOBS[NAME]["handler"]
    registry.handler(NAME)(handle)
    ids = {await _add() for _ in range(30)}

    async def loop(who: str) -> int:
        done = 0
        while await worker.run_one(session_factory, [QUEUE], who):
            done += 1
        return done

    counts = await asyncio.gather(loop("a"), loop("b"))
    assert sum(counts) == 30
    assert sorted(ran) == sorted(ids)  # each id once: no job ran twice, none was lost
    assert await _count(Job.status == SUCCEEDED) == 30


async def test_a_job_under_a_lease_cannot_be_claimed_again() -> None:
    await _add()
    first = await queue.claim(session_factory, [QUEUE], "a")
    assert first is not None
    assert await queue.claim(session_factory, [QUEUE], "b") is None
    row = await _row(first.id)
    assert (row.status, row.attempts, row.locked_by) == (RUNNING, 1, "a")


async def test_concurrent_claims_never_hand_one_job_to_two_workers() -> None:
    for _ in range(10):
        await _add()
    results = await asyncio.gather(*[queue.claim(session_factory, [QUEUE], f"w{i}") for i in range(10)])
    ids = [r.id for r in results if r is not None]
    assert len(ids) == len(set(ids)) == 10


# --- retry, dead letter -----------------------------------------------------------------------


async def test_a_failed_run_waits_for_its_backoff_then_runs_again() -> None:
    t0 = _now()
    job_id = await _add(now=t0)
    first = await queue.claim(session_factory, [QUEUE], "w", now=t0)
    assert first is not None and first.attempt == 1
    outcome = await queue.fail(session_factory, first, RuntimeError("password=hunter2"), now=t0)
    delay = queue.backoff_delay(RETRY, 1)
    row = await _row(job_id)
    if MAX_ATTEMPTS == 1:
        assert outcome == "dead" and row.status == DEAD
        return
    assert outcome == "retry" and row.status == PENDING
    assert row.run_at == t0 + dt.timedelta(seconds=delay)
    assert row.last_error == "RuntimeError"  # the class only: never the message
    assert await queue.claim(session_factory, [QUEUE], "w", now=t0 + dt.timedelta(seconds=delay - 1)) is None
    second = await queue.claim(session_factory, [QUEUE], "w", now=t0 + dt.timedelta(seconds=delay))
    assert second is not None and second.attempt == 2 and second.lease_token != first.lease_token


async def test_a_job_that_keeps_failing_ends_dead_after_its_cap_and_can_be_requeued() -> None:
    t0 = _now()
    job_id = await _add(now=t0)
    clock = t0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        claimed = await queue.claim(session_factory, [QUEUE], "w", now=clock)
        assert claimed is not None and claimed.attempt == attempt
        outcome = await queue.fail(session_factory, claimed, "boom", now=clock)
        clock += dt.timedelta(seconds=queue.backoff_delay(RETRY, attempt) + 1)
        assert outcome == ("dead" if attempt == MAX_ATTEMPTS else "retry")
    row = await _row(job_id)
    assert (row.status, row.attempts, row.last_error) == (DEAD, MAX_ATTEMPTS, "boom")
    assert await queue.claim(session_factory, [QUEUE], "w", now=clock + dt.timedelta(days=30)) is None
    async with session_factory() as session:
        assert [j.id for j in await queue.list_dead(session)] == [job_id]
        assert await queue.requeue_dead(session, job_id) == 1
        await session.commit()
    again = await queue.claim(session_factory, [QUEUE], "w")
    assert again is not None and again.id == job_id and again.attempt == 1


async def test_a_handler_error_is_recorded_without_its_message() -> None:
    async def handle(ctx: registry.JobContext) -> None:
        raise ValueError("card 4111111111111111")

    handle.__name__ = definitions.JOBS[NAME]["handler"]
    registry.handler(NAME)(handle)
    job_id = await _add()
    assert await worker.run_one(session_factory, [QUEUE], "w") is True
    row = await _row(job_id)
    assert row.last_error == "ValueError"
    assert "4111" not in repr(row.last_error)


async def test_a_handler_past_its_timeout_is_cancelled_and_counts_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled: list[bool] = []

    async def handle(ctx: registry.JobContext) -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    handle.__name__ = definitions.JOBS[NAME]["handler"]
    registry.handler(NAME)(handle)
    monkeypatch.setitem(definitions.JOBS, NAME, {**definitions.JOBS[NAME], "timeout_seconds": 0.2})
    job_id = await _add()
    assert await worker.run_one(session_factory, [QUEUE], "w") is True
    row = await _row(job_id)
    assert cancelled == [True]
    assert row.last_error == "Timeout"
    assert row.status in (PENDING, DEAD) and row.lease_token is None


# --- the lease --------------------------------------------------------------------------------


async def test_a_job_whose_worker_died_is_delivered_again_after_the_lease_expires() -> None:
    t0 = _now()
    job_id = await _add(now=t0)
    dead_worker = await queue.claim(session_factory, [QUEUE], "crashed", now=t0)
    assert dead_worker is not None
    lease = dt.timedelta(seconds=queue.lease_seconds(NAME))
    assert await queue.claim(session_factory, [QUEUE], "b", now=t0 + lease - dt.timedelta(seconds=1)) is None
    if MAX_ATTEMPTS == 1:
        return  # no second run is allowed: see the next test
    again = await queue.claim(session_factory, [QUEUE], "b", now=t0 + lease + dt.timedelta(seconds=1))
    assert again is not None and again.id == job_id and again.attempt == 2
    assert again.lease_token != dead_worker.lease_token
    # the first worker wakes up late: its answer is ignored, the new holder's counts
    assert await queue.complete(session_factory, dead_worker) is False
    assert await queue.fail(session_factory, dead_worker, "late") == "lost"
    assert (await _row(job_id)).status == RUNNING
    assert await queue.complete(session_factory, again) is True
    row = await _row(job_id)
    assert (row.status, row.attempts, row.lease_token) == (SUCCEEDED, 2, None)


async def test_a_job_that_loses_its_lease_on_the_last_attempt_is_parked_dead() -> None:
    t0 = _now()
    job_id = await _add(now=t0)
    lease = dt.timedelta(seconds=queue.lease_seconds(NAME) + 1)
    clock = t0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        claimed = await queue.claim(session_factory, [QUEUE], "crashes", now=clock)
        assert claimed is not None and claimed.attempt == attempt
        clock += lease
    assert await queue.claim(session_factory, [QUEUE], "b", now=clock) is None
    row = await _row(job_id)
    assert (row.status, row.last_error, row.attempts) == (DEAD, "LeaseExpired", MAX_ATTEMPTS)


async def test_old_succeeded_jobs_are_purged_and_free_their_dedupe_key() -> None:
    t0 = _now()
    job_id = await queue.enqueue(NAME, {}, dedupe_key="k", now=t0)
    assert job_id is not None
    claimed = await queue.claim(session_factory, [QUEUE], "w", now=t0)
    assert claimed is not None
    await queue.complete(session_factory, claimed, now=t0)
    async with session_factory() as session:
        assert await queue.purge_succeeded(session, now=t0 + dt.timedelta(days=1)) == 0
        assert await queue.purge_succeeded(session, now=t0 + dt.timedelta(days=config.retention_days() + 1)) == 1
    assert await queue.enqueue(NAME, {}, dedupe_key="k") is not None


async def test_a_dedupe_key_is_unique_per_tenant() -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    first = await queue.enqueue(NAME, {}, dedupe_key="same", tenant_id=tenant_a)
    other = await queue.enqueue(NAME, {}, dedupe_key="same", tenant_id=tenant_b)
    again = await queue.enqueue(NAME, {}, dedupe_key="same", tenant_id=tenant_a)
    tenantless = await queue.enqueue(NAME, {}, dedupe_key="same")
    assert first is not None and other is not None and tenantless is not None
    assert again is None  # the same tenant's second enqueue is the duplicate
    assert await queue.enqueue(NAME, {}, dedupe_key="same") is None


async def test_old_schedule_fire_records_are_purged_but_the_newest_of_each_schedule_stays() -> None:
    t0 = _now()
    old = t0 - dt.timedelta(days=config.fire_retention_days() + 5)
    async with session_factory() as session:
        for schedule, offset in (("s1", 3), ("s1", 2), ("s1", 1), ("s2", 3)):
            tick = old - dt.timedelta(days=offset)
            session.add(ScheduleFire(schedule=schedule, fire_time=tick, outcome="skipped", created_at=tick))
        recent = ScheduleFire(schedule="s1", fire_time=t0, outcome="skipped", created_at=t0)
        session.add(recent)
        await session.commit()
        await queue.purge_succeeded(session, now=t0)
    left = sorted((f.schedule, f.fire_time) for f in await _all_fires())
    assert left == [("s1", t0), ("s2", old - dt.timedelta(days=3))]


async def _all_fires() -> list[ScheduleFire]:
    async with session_factory() as session:
        return list((await session.scalars(sa.select(ScheduleFire))).all())



# --- schedules --------------------------------------------------------------------------------

SCHEDULE = "nightly_invoices"
SCHEDULED_JOB = "send_invoice"
CFG = definitions.SCHEDULES[SCHEDULE]


def _tick_after(moment: dt.datetime, count: int = 1) -> dt.datetime:
    spec, tz = cron.parse(CFG["cron"]), cron.zone(CFG["timezone"])
    tick = moment
    for _ in range(count):
        found = cron.next_fire(spec, tz, tick)
        assert found is not None
        tick = found
    return tick


async def _scheduled() -> list[Job]:
    async with session_factory() as session:
        return list((await session.scalars(sa.select(Job).where(Job.name == SCHEDULED_JOB))).all())


async def _fires() -> list[ScheduleFire]:
    async with session_factory() as session:
        return list((await session.scalars(sa.select(ScheduleFire).order_by(ScheduleFire.fire_time))).all())


async def test_a_schedule_seen_for_the_first_time_does_not_replay_the_past() -> None:
    t0 = _now()
    assert await scheduler.fire_due(session_factory, t0) == []
    assert await _scheduled() == []


async def test_each_tick_fires_once_however_many_schedulers_run() -> None:
    t0 = _now()
    await scheduler.fire_due(session_factory, t0)  # first sight: the baseline
    tick = _tick_after(t0)
    now = tick + dt.timedelta(seconds=2)
    results = await asyncio.gather(*[scheduler.fire_due(session_factory, now) for _ in range(8)])
    assert sum(1 for r in results for name, _ in r if name == SCHEDULE) == 1
    jobs = await _scheduled()
    assert len(jobs) == 1 and jobs[0].payload["schedule"] == SCHEDULE
    assert [f.fire_time for f in await _fires()] == [tick]
    assert await scheduler.fire_due(session_factory, now + dt.timedelta(seconds=1)) == []  # same tick: nothing
    next_tick = _tick_after(tick)
    again = await asyncio.gather(*[scheduler.fire_due(session_factory, next_tick) for _ in range(5)])
    assert sum(len(r) for r in again) == 1
    assert len(await _scheduled()) == 2


async def test_many_missed_ticks_catch_up_at_most_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(definitions.SCHEDULES, SCHEDULE, {**CFG, "missed": "catch_up_one"})
    t0 = _now()
    await scheduler.fire_due(session_factory, t0)
    late = _tick_after(t0, 5) + dt.timedelta(hours=1)  # five ticks went by while everything was down
    fired = await asyncio.gather(*[scheduler.fire_due(session_factory, late) for _ in range(3)])
    assert sum(len(r) for r in fired) == 1
    assert len(await _scheduled()) == 1


async def test_missed_ticks_are_dropped_when_the_policy_says_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(definitions.SCHEDULES, SCHEDULE, {**CFG, "missed": "skip"})
    t0 = _now()
    await scheduler.fire_due(session_factory, t0)
    tick = _tick_after(t0)
    late = tick + dt.timedelta(seconds=config.scheduler_grace() + 60)
    if _tick_after(tick) <= late:
        pytest.skip("this schedule ticks more often than the grace period: nothing is ever late enough to skip")
    assert await scheduler.fire_due(session_factory, late) == []
    assert await _scheduled() == []
    assert [f.outcome for f in await _fires()] == ["skipped"]
    assert await scheduler.fire_due(session_factory, late) == []  # decided once


async def test_a_disabled_schedule_never_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(definitions.SCHEDULES, SCHEDULE, {**CFG, "enabled": False})
    t0 = _now()
    await scheduler.fire_due(session_factory, t0)
    assert await scheduler.fire_due(session_factory, _tick_after(t0) + dt.timedelta(seconds=1)) == []
    assert await _scheduled() == []


async def test_a_tick_whose_transaction_never_committed_is_fired_by_the_next_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t0 = _now()
    await scheduler.fire_due(session_factory, t0)
    now = _tick_after(t0) + dt.timedelta(seconds=1)
    real = queue.enqueue

    async def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("process died before commit")

    monkeypatch.setattr(queue, "enqueue", explode)
    with pytest.raises(RuntimeError):
        await scheduler.fire_due(session_factory, now)
    assert await _fires() == [] and await _scheduled() == []  # nothing half-done
    monkeypatch.setattr(queue, "enqueue", real)
    assert len(await scheduler.fire_due(session_factory, now)) == 1
