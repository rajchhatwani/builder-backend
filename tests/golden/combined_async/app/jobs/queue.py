"""The Postgres job queue (generated): enqueue, claim under a lease, finish, retry, dead-letter.

A job row is claimed with FOR UPDATE SKIP LOCKED in a short transaction that stamps a fresh lease token and an
expiry; the handler then runs OUTSIDE any database transaction. Finishing is a conditional UPDATE that
only matches while the lease token is still ours: a worker that stalled past its lease and lost the job
cannot overwrite the outcome of the worker that has it now. A job whose lease ran out (the worker died) is
claimed again, and after `max_attempts` starts it is parked as `dead` instead of being run for ever.

Times come from `now` (default: the clock of this host). Keep hosts on NTP; a lease is at least the job's
timeout plus JOBS_LEASE_GRACE_SECONDS, which is far more than any sane skew.
"""

import datetime as _dt
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs import config, definitions
from app.jobs.models import DEAD, PENDING, RUNNING, SUCCEEDED, Job, ScheduleFire
from app.models._base import utcnow

logger = structlog.get_logger()

SessionFactory = async_sessionmaker[AsyncSession]


class UnknownJob(ValueError):
    """The job name is not declared in the spec."""


@dataclass(frozen=True)
class Claimed:
    id: uuid.UUID
    name: str
    queue: str
    payload: dict[str, Any]
    attempt: int
    max_attempts: int
    lease_token: uuid.UUID
    timeout_seconds: float


def backoff_delay(retry: Mapping[str, Any], attempt: int) -> float:
    """Seconds to wait after failed run number `attempt` (1-based): fixed, or doubling up to a cap."""
    base = float(retry["backoff_seconds"])
    if retry["backoff"] == "fixed":
        return min(base, config.BACKOFF_CAP_SECONDS)
    return min(base * 2 ** max(attempt - 1, 0), config.BACKOFF_CAP_SECONDS)


def lease_seconds(job_name: str) -> float:
    """How long a claim is held: the job's timeout plus a grace, so a live handler never loses its lease
    before its timeout cancels it."""
    return float(definitions.JOBS[job_name]["timeout_seconds"]) + config.lease_grace()


def _describe(exc: BaseException) -> str:
    """What is stored about a failure: the class name only (a message may carry a payload or a secret)."""
    return type(exc).__name__[: config.MAX_ERROR_CHARS]


async def enqueue(
    name: str,
    payload: dict[str, Any] | None = None,
    *,
    session: AsyncSession | None = None,
    run_at: _dt.datetime | None = None,
    dedupe_key: str | None = None,
    tenant_id: uuid.UUID | None = None,
    now: _dt.datetime | None = None,
) -> uuid.UUID | None:
    """Add a job; with `session` it is part of the caller's transaction (commit/rollback is the caller's),
    without it a transaction of its own commits it. Returns the id, or None if `dedupe_key` already exists.

    A `dedupe_key` is unique per `tenant_id`: in a multi-tenant project pass the tenant, so one tenant's
    key can never swallow another's job. Without a tenant the key is unique among tenant-less jobs."""
    declared = definitions.JOBS.get(name)
    if declared is None:
        raise UnknownJob(f"unknown job {name!r}")
    body = {} if payload is None else payload
    if not isinstance(body, dict):
        raise TypeError("a job payload is a dict")
    try:
        size = len(json.dumps(body, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise ValueError("a job payload must be JSON (no NaN, no custom objects)") from None
    if size > config.MAX_PAYLOAD_BYTES:
        raise ValueError(f"a job payload is at most {config.MAX_PAYLOAD_BYTES} bytes")
    if dedupe_key is not None and not 0 < len(dedupe_key) <= 200:
        raise ValueError("dedupe_key is 1 to 200 characters")
    stamp = now or utcnow()
    if run_at is not None and run_at.tzinfo is None:
        raise ValueError("run_at must be timezone-aware")
    values = {
        "id": uuid.uuid4(),
        "name": name,
        "queue": declared["queue"],
        "payload": body,
        "status": PENDING,
        "attempts": 0,
        "max_attempts": declared["retry"]["max_attempts"],
        "run_at": run_at or stamp,
        "dedupe_key": dedupe_key,
        "tenant_id": tenant_id,
        "created_at": stamp,
    }
    # no conflict target: either partial unique index (tenant-less / per tenant) may decide
    stmt = pg_insert(Job).values(**values).on_conflict_do_nothing().returning(Job.id)
    if session is not None:
        return (await session.execute(stmt)).scalar_one_or_none()
    from app.db import session_factory

    async with session_factory() as own:
        job_id = (await own.execute(stmt)).scalar_one_or_none()
        await own.commit()
        return job_id


async def claim(
    factory: SessionFactory,
    queues: list[str] | tuple[str, ...],
    worker_id: str,
    *,
    now: _dt.datetime | None = None,
) -> Claimed | None:
    """Take the next due job of `queues` (or one whose lease ran out) under a fresh lease. None if none is due."""
    while True:
        async with factory() as session:
            stamp = now or utcnow()
            due = sa.or_(
                sa.and_(Job.status == PENDING, Job.run_at <= stamp),
                sa.and_(Job.status == RUNNING, Job.lease_expires_at <= stamp),
            )
            stmt = (
                sa.select(Job)
                .where(Job.queue.in_(list(queues)), due)
                .order_by(Job.run_at, Job.created_at, Job.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = (await session.scalars(stmt)).first()
            if row is None:
                await session.rollback()
                return None
            declared = definitions.JOBS.get(row.name)
            if declared is None or row.attempts >= row.max_attempts:
                # A removed job, or a job that already started its last attempt and lost its lease again.
                row.status = DEAD
                row.last_error = "UnknownJob" if declared is None else "LeaseExpired"
                row.lease_token = None
                row.lease_expires_at = None
                row.finished_at = stamp
                logger.error("job_dead_lettered", job_id=str(row.id), job=row.name, attempts=row.attempts)
                await session.commit()
                continue
            token = uuid.uuid4()
            row.status = RUNNING
            row.attempts += 1
            row.lease_token = token
            row.lease_expires_at = stamp + _dt.timedelta(seconds=lease_seconds(row.name))
            row.locked_by = worker_id[:80]
            claimed = Claimed(
                id=row.id,
                name=row.name,
                queue=row.queue,
                payload=dict(row.payload),
                attempt=row.attempts,
                max_attempts=row.max_attempts,
                lease_token=token,
                timeout_seconds=float(declared["timeout_seconds"]),
            )
            await session.commit()
            return claimed


async def complete(factory: SessionFactory, job: Claimed, *, now: _dt.datetime | None = None) -> bool:
    """Mark the job succeeded, only if the lease is still ours. False = the lease was lost (ignored)."""
    stamp = now or utcnow()
    async with factory() as session:
        result = await session.execute(
            sa.update(Job)
            .where(Job.id == job.id, Job.lease_token == job.lease_token, Job.status == RUNNING)
            .values(
                status=SUCCEEDED,
                finished_at=stamp,
                lease_token=None,
                lease_expires_at=None,
                last_error=None,
            )
            .returning(Job.id)
        )
        won = result.scalar_one_or_none() is not None
        await session.commit()
    if not won:
        logger.warning("job_lease_lost", job_id=str(job.id), job=job.name)
    return won


async def fail(
    factory: SessionFactory, job: Claimed, error: BaseException | str, *, now: _dt.datetime | None = None
) -> str:
    """Record a failed run: retry with backoff, or dead after the cap. Returns retry | dead | lost."""
    stamp = now or utcnow()
    text = error if isinstance(error, str) else _describe(error)
    retry = definitions.JOBS[job.name]["retry"]
    last = job.attempt >= job.max_attempts
    values: dict[str, Any] = {"last_error": text[: config.MAX_ERROR_CHARS], "lease_token": None, "lease_expires_at": None}
    if last:
        values.update(status=DEAD, finished_at=stamp)
    else:
        values.update(status=PENDING, run_at=stamp + _dt.timedelta(seconds=backoff_delay(retry, job.attempt)))
    async with factory() as session:
        result = await session.execute(
            sa.update(Job)
            .where(Job.id == job.id, Job.lease_token == job.lease_token, Job.status == RUNNING)
            .values(**values)
            .returning(Job.id)
        )
        won = result.scalar_one_or_none() is not None
        await session.commit()
    if not won:
        logger.warning("job_lease_lost", job_id=str(job.id), job=job.name)
        return "lost"
    if last:
        logger.error("job_dead_lettered", job_id=str(job.id), job=job.name, attempts=job.attempt, error=text)
        return "dead"
    return "retry"


async def list_dead(session: AsyncSession, limit: int = 100) -> list[Job]:
    stmt = sa.select(Job).where(Job.status == DEAD).order_by(Job.finished_at, Job.id).limit(limit)
    return list((await session.scalars(stmt)).all())


async def requeue_dead(session: AsyncSession, job_id: uuid.UUID | None = None, *, now: _dt.datetime | None = None) -> int:
    """Give dead jobs a fresh set of attempts (one job, or all of them). The caller commits."""
    stamp = now or utcnow()
    stmt = sa.update(Job).where(Job.status == DEAD)
    if job_id is not None:
        stmt = stmt.where(Job.id == job_id)
    result = await session.execute(
        stmt.values(status=PENDING, attempts=0, run_at=stamp, finished_at=None, last_error=None)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def purge_succeeded(session: AsyncSession, *, now: _dt.datetime | None = None) -> int:
    """Delete succeeded jobs older than the retention (this also frees their dedupe keys), and
    schedule-fire records older than JOBS_SCHEDULE_FIRE_RETENTION_DAYS (default 30). The newest fire of
    each schedule is always kept: the scheduler never fires a tick earlier than it. Returns the number
    of jobs removed."""
    stamp = now or utcnow()
    cutoff = stamp - _dt.timedelta(days=config.retention_days())
    result = await session.execute(
        sa.delete(Job).where(Job.status == SUCCEEDED, Job.finished_at < cutoff)
    )
    latest = sa.alias(ScheduleFire.__table__, name="latest")
    newest_fire = (
        sa.select(sa.func.max(latest.c.fire_time)).where(latest.c.schedule == ScheduleFire.schedule).scalar_subquery()
    )
    await session.execute(
        sa.delete(ScheduleFire).where(
            ScheduleFire.created_at < stamp - _dt.timedelta(days=config.fire_retention_days()),
            ScheduleFire.fire_time < newest_fire,
        )
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
