"""Payments worker (generated): runs the queued jobs and the periodic maintenance.

    python -m app.payments.worker

Run as many of these as the load needs, on this machine or on others. A worker needs only the
DATABASE_URL and the provider settings; it talks to no other worker. Jobs are claimed with
`FOR UPDATE SKIP LOCKED` and leased, so every job runs on one worker at a time, and a job whose
worker dies is picked up by another after the lease runs out. Stopping a worker (SIGTERM) lets the
jobs in flight finish.
"""

import asyncio
import contextlib
import random
import signal
import socket
import uuid
from datetime import UTC, datetime, timedelta

import structlog

from app.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db import engine, session_factory
from app.payments import audit, config, events, jobs, reconcile, service
from app.payments.lock import ensure_payments_lock
from app.payments.providers.base import ProviderError

logger = structlog.get_logger()
_SHUTDOWN_GRACE_SECONDS = 25
_SCHEDULE_EVERY_SECONDS = 15


def worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"


async def handle(job: jobs.ClaimedJob) -> None:
    """Run one job. Raise to have it retried; the exception's code is kept, its text is not."""
    payload = job.payload
    async with session_factory() as session:
        if job.type == jobs.PROCESS_EVENT:
            await events.process_event(session, uuid.UUID(payload["event_id"]))
        elif job.type == jobs.DISPATCH_REFUND:
            await service.dispatch_refund(session, uuid.UUID(payload["refund_id"]))
        elif job.type == jobs.FINISH_PAYMENT:
            await service.finish_payment(session, uuid.UUID(payload["payment_id"]))
        elif job.type == jobs.RECONCILE:
            await reconcile.run()
        elif job.type == jobs.RETENTION:
            await run_retention()
        elif job.type == jobs.AUDIT_DIGEST:
            await log_digest(payload.get("day"))
        else:
            raise ValueError(f"unknown job type {job.type!r}")


async def run_retention() -> None:
    from app.payments import idempotency

    settings = config.get_payments_settings()
    async with session_factory() as session:
        keys = await idempotency.purge_expired(session)
        old_events = await events.purge_old_events(session, settings.payments_webhook_events_retention_days)
        finished = await jobs.purge_finished(session, settings.payments_jobs_retention_days)
        await session.commit()
    logger.info("retention_done", idempotency_keys=keys, events=old_events, jobs=finished)


async def log_digest(day: str | None) -> None:
    """Log the digest of one day's audit entries (default: yesterday). Ship these log lines to
    storage you control: they let you prove later that the audit table was not rewritten."""
    moment = datetime.fromisoformat(day) if day else datetime.now(UTC) - timedelta(days=1)
    async with session_factory() as session:
        digest = await audit.day_digest(session, moment)
    logger.info("audit_digest", day=moment.date().isoformat(), sha256=digest)


async def _run_job(job: jobs.ClaimedJob) -> None:
    try:
        if job.attempts > job.max_attempts:
            raise _GaveUp("attempts_exhausted")
        await handle(job)
    except _GaveUp as exc:
        await _record_failure(job, exc.code, retry=False)
    except (events.EventRetry, ProviderError, AppError) as exc:
        await _record_failure(job, exc.code, retry=True)
    except Exception as exc:
        logger.exception("job_failed", job_type=job.type)
        await _record_failure(job, type(exc).__name__, retry=True)
    else:
        async with session_factory() as session:
            await jobs.complete(session, job.id)
            await session.commit()


class _GaveUp(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def _record_failure(job: jobs.ClaimedJob, code: str, *, retry: bool) -> None:
    async with session_factory() as session:
        dead = await jobs.fail(session, job, code, retry=retry)
        if dead:
            logger.error("job_dead", job_type=job.type, job_id=str(job.id), code=code)
            await audit.append(
                session,
                payment_id=None,
                event="job_dead",
                data={"job_type": job.type, "job_id": str(job.id), "code": code},
            )
        await session.commit()


async def schedule_periodic(now: datetime | None = None) -> None:
    """Enqueue the recurring jobs. A time-bucket dedupe key makes this safe to call from every
    worker at once: only one job per bucket is ever created."""
    moment = now or datetime.now(UTC)
    stamp = int(moment.timestamp())
    day = (moment - timedelta(days=1)).date().isoformat()
    async with session_factory() as session:
        await jobs.enqueue(session, jobs.RECONCILE, {}, dedupe_key=f"reconcile:{stamp // 60}")
        await jobs.enqueue(session, jobs.RETENTION, {}, dedupe_key=f"retention:{stamp // 21600}")
        await jobs.enqueue(session, jobs.AUDIT_DIGEST, {"day": day}, dedupe_key=f"digest:{day}")
        await session.commit()


async def run_once(*, limit: int = 100, name: str | None = None) -> int:
    """Claim and run due jobs one at a time until none are left (or `limit`). Used by tests and
    by `make` targets; the long-running worker uses `run_worker`."""
    me = name or worker_id()
    done = 0
    lease = config.get_payments_settings().payments_job_lease_seconds
    while done < limit:
        async with session_factory() as session:
            claimed = await jobs.claim(session, worker_id=me, limit=1, lease_seconds=lease)
            await session.commit()
        if not claimed:
            return done
        await _run_job(claimed[0])
        done += 1
    return done


async def run_worker(stop: asyncio.Event) -> None:
    settings = config.get_payments_settings()
    me = worker_id()
    running: set[asyncio.Task[None]] = set()
    last_schedule = 0.0
    logger.info("worker_started", worker=me, concurrency=settings.payments_worker_concurrency)
    while not stop.is_set():
        free = settings.payments_worker_concurrency - len(running)
        claimed: list[jobs.ClaimedJob] = []
        if free > 0:
            async with session_factory() as session:
                claimed = await jobs.claim(
                    session, worker_id=me, limit=free, lease_seconds=settings.payments_job_lease_seconds
                )
                await session.commit()
        for job in claimed:
            task = asyncio.create_task(_run_job(job))
            running.add(task)
            task.add_done_callback(running.discard)
        loop_time = asyncio.get_running_loop().time()
        if settings.payments_scheduler and loop_time - last_schedule >= _SCHEDULE_EVERY_SECONDS:
            last_schedule = loop_time
            await schedule_periodic()
        # Come straight back when the batch was full (there is probably more); else wait a beat.
        pause = 0.0 if len(claimed) == free and free > 0 else settings.payments_poll_interval_seconds
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=pause * random.uniform(0.8, 1.2))  # noqa: S311
    if running:
        logger.info("worker_draining", jobs=len(running))
        await asyncio.wait(running, timeout=_SHUTDOWN_GRACE_SECONDS)
    logger.info("worker_stopped", worker=me)


async def main() -> None:
    configure_logging(get_settings().log_level)
    await ensure_payments_lock()  # checks the settings too: a bad key stops the worker here
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not available on Windows
            loop.add_signal_handler(sig, stop.set)
    try:
        await run_worker(stop)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
