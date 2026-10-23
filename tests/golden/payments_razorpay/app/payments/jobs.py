"""A small job queue on Postgres (generated): enqueue, claim, complete, retry, dead-letter.

Any number of worker processes on any number of machines can run against the same database:
`FOR UPDATE SKIP LOCKED` hands each job to exactly one of them, and a lease (`locked_until`) lets
another worker take over the job of one that crashed. Jobs carry ids only (never personal data);
handlers must be idempotent because a job can run more than once.
"""

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments import config
from app.payments.models import Job

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
DEAD = "dead"

# job types
PROCESS_EVENT = "process_event"
DISPATCH_REFUND = "dispatch_refund"
FINISH_PAYMENT = "finish_payment"  # retry the provider call of a payment stuck in `creating`
RECONCILE = "reconcile"
RETENTION = "retention"
AUDIT_DIGEST = "audit_digest"


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    type: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


def backoff_seconds(attempts: int) -> float:
    """Exponential backoff with jitter: 5s, 10s, 20s ... capped at one hour."""
    base = min(3600.0, 5.0 * (2 ** max(0, attempts - 1)))
    return base * random.uniform(0.5, 1.5)  # noqa: S311 - jitter, not security


async def enqueue(
    session: AsyncSession,
    job_type: str,
    payload: dict[str, Any],
    *,
    run_at: datetime | None = None,
    dedupe_key: str | None = None,
    max_attempts: int | None = None,
) -> uuid.UUID | None:
    """Add a job in the caller's transaction. With a dedupe_key, a second enqueue is a no-op."""
    stmt = (
        insert(Job)
        .values(
            id=uuid.uuid4(),
            type=job_type,
            payload=payload,
            status=QUEUED,
            run_at=run_at or datetime.now(UTC),
            attempts=0,
            max_attempts=max_attempts or config.get_payments_settings().payments_job_max_attempts,
            dedupe_key=dedupe_key,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Job.id)
    )
    row = (await session.execute(stmt)).first()
    return row[0] if row is not None else None


async def claim(
    session: AsyncSession, *, worker_id: str, limit: int, lease_seconds: int
) -> list[ClaimedJob]:
    """Take up to `limit` runnable jobs (queued and due, or running with an expired lease)."""
    rows = (
        await session.execute(
            sa.text(
                """
                UPDATE pay_jobs SET status = 'running', locked_by = :worker,
                       locked_until = now() + make_interval(secs => :lease),
                       attempts = attempts + 1, updated_at = now()
                WHERE id IN (
                    SELECT id FROM pay_jobs
                    WHERE (status = 'queued' AND run_at <= now())
                       OR (status = 'running' AND locked_until < now())
                    ORDER BY run_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT :limit
                )
                RETURNING id, type, payload, attempts, max_attempts
                """
            ),
            {"worker": worker_id, "lease": float(lease_seconds), "limit": limit},
        )
    ).all()
    return [ClaimedJob(r[0], r[1], r[2], r[3], r[4]) for r in rows]


async def complete(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        sa.update(Job)
        .where(Job.id == job_id)
        .values(status=DONE, locked_by=None, locked_until=None, last_error_code=None)
    )


async def fail(
    session: AsyncSession, job: ClaimedJob, error_code: str, *, retry: bool = True
) -> bool:
    """Reschedule the job, or dead-letter it when attempts are used up. True if dead-lettered."""
    dead = (not retry) or job.attempts >= job.max_attempts
    values: dict[str, Any] = {
        "last_error_code": error_code[:64],
        "locked_by": None,
        "locked_until": None,
    }
    if dead:
        values["status"] = DEAD
    else:
        values["status"] = QUEUED
        values["run_at"] = datetime.now(UTC) + timedelta(seconds=backoff_seconds(job.attempts))
    await session.execute(sa.update(Job).where(Job.id == job.id).values(**values))
    return dead


async def retry_dead(session: AsyncSession, job_id: uuid.UUID) -> bool:
    result = await session.execute(
        sa.update(Job)
        .where(Job.id == job_id, Job.status == DEAD)
        .values(status=QUEUED, attempts=0, run_at=datetime.now(UTC), last_error_code=None)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def queue_stats(session: AsyncSession) -> dict[str, Any]:
    counts = dict(
        (
            await session.execute(sa.select(Job.status, sa.func.count()).group_by(Job.status))
        ).all()
    )
    oldest = (
        await session.execute(
            sa.select(sa.func.min(Job.run_at)).where(Job.status == QUEUED, Job.run_at <= sa.func.now())
        )
    ).scalar_one()
    lag = (datetime.now(UTC) - oldest).total_seconds() if oldest is not None else 0.0
    return {
        "queued": counts.get(QUEUED, 0),
        "running": counts.get(RUNNING, 0),
        "dead": counts.get(DEAD, 0),
        "oldest_due_seconds": round(max(lag, 0.0), 1),
    }


async def purge_finished(session: AsyncSession, older_than_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    result = await session.execute(
        sa.delete(Job).where(Job.status == DONE, Job.updated_at < cutoff)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
