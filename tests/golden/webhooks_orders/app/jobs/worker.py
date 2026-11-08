"""The job worker (generated).

    python -m app.jobs.worker --group NAME          run until SIGTERM / Ctrl-C
    python -m app.jobs.worker --group NAME --once   run what is due now, then exit

A process runs the group's `concurrency` jobs at a time (JOBS_CONCURRENCY overrides) and, unless
JOBS_SCHEDULER_ENABLED=false, the cron scheduler. Start as many processes, on as many machines, as the load
needs: claiming is FOR UPDATE SKIP LOCKED under a lease (see queue.py), so a job never runs twice at once.
Size the database pool for it: DB_POOL_SIZE at least concurrency + 2 (the compose files do).
On SIGTERM the worker stops taking jobs and waits for the running ones to finish.
"""

import argparse
import asyncio
import contextlib
import os
import signal
import socket
import sys
import time
import uuid

import structlog

from app.jobs import config, definitions, queue, registry, scheduler
from app.jobs.queue import SessionFactory

logger = structlog.get_logger()


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


async def run_one(factory: SessionFactory, queues: list[str] | tuple[str, ...], who: str) -> bool:
    """Claim one due job, run it, record the outcome. False when nothing was due."""
    job = await queue.claim(factory, queues, who)
    if job is None:
        return False
    fn = registry.get(job.name)
    started = time.monotonic()
    logger.info("job_started", job_id=str(job.id), job=job.name, attempt=job.attempt)
    if fn is None:
        await queue.fail(factory, job, "NoHandler")
        return True
    ctx = registry.JobContext(
        job_id=job.id, name=job.name, attempt=job.attempt, max_attempts=job.max_attempts, payload=job.payload
    )
    try:
        await asyncio.wait_for(fn(ctx), job.timeout_seconds)
    except TimeoutError:
        outcome = await queue.fail(factory, job, "Timeout")
        logger.error("job_timed_out", job_id=str(job.id), job=job.name, outcome=outcome)
    except asyncio.CancelledError:
        raise  # shutdown: the lease runs out and the job is claimed again
    except Exception as exc:
        outcome = await queue.fail(factory, job, exc)
        logger.error("job_failed", job_id=str(job.id), job=job.name, error=type(exc).__name__, outcome=outcome)
    else:
        await queue.complete(factory, job)
        logger.info("job_succeeded", job_id=str(job.id), job=job.name, seconds=round(time.monotonic() - started, 3))
    return True


async def drain(factory: SessionFactory, queues: list[str] | tuple[str, ...], who: str, limit: int = 10_000) -> int:
    done = 0
    while done < limit and await run_one(factory, queues, who):
        done += 1
    return done


async def _slot(factory: SessionFactory, queues: list[str], who: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            if await run_one(factory, queues, who):
                continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the database may be briefly away: log the class, try again
            logger.error("worker_error", error=type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), config.poll_interval())


async def _purger(factory: SessionFactory, stop: asyncio.Event) -> None:
    from app.jobs.queue import purge_succeeded

    while not stop.is_set():
        try:
            async with factory() as session:
                await purge_succeeded(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("purge_error", error=type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), 3600.0)


async def run_forever(factory: SessionFactory, group: str, stop: asyncio.Event) -> None:
    cfg = definitions.GROUPS[group]
    who = worker_id()
    slots = config.concurrency(cfg["concurrency"])
    logger.info("worker_started", group=group, queues=cfg["queues"], concurrency=slots)
    tasks = [asyncio.create_task(_slot(factory, cfg["queues"], who, stop)) for _ in range(slots)]
    tasks.append(asyncio.create_task(_purger(factory, stop)))
    if config.scheduler_enabled():
        tasks.append(asyncio.create_task(scheduler.run_scheduler(factory, stop)))
    await asyncio.gather(*tasks)  # each ends when `stop` is set, after its current job
    logger.info("worker_stopped", group=group)


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.jobs.worker")
    parser.add_argument("--group", required=True, choices=sorted(definitions.GROUPS))
    parser.add_argument("--once", action="store_true", help="run what is due now, then exit")
    return parser.parse_args(argv)


async def _main(args: argparse.Namespace) -> None:
    from app.db import engine, session_factory

    registry.load_handlers()  # a job without a handler stops the worker here
    stop = asyncio.Event()
    try:
        if args.once:
            await drain(session_factory, definitions.GROUPS[args.group]["queues"], worker_id())
            return
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_forever(session_factory, args.group, stop)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main(_parse(sys.argv[1:])))
