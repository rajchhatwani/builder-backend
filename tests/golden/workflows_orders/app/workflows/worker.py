"""The workflow worker (generated).

    python -m app.workflows.worker           run until SIGTERM / Ctrl-C
    python -m app.workflows.worker --once    run what is due now, then exit

A process drives WORKFLOWS_CONCURRENCY runs at a time (default: the spec's worker.concurrency). Start as many
processes, on as many machines, as the load needs: claiming is FOR UPDATE SKIP LOCKED under a lease, so a run
is never driven by two workers at once. If a process is killed, its runs are picked up by another worker once
the lease runs out, and continue after the last recorded step. Size the database pool: DB_POOL_SIZE at
least concurrency + 2 (the compose file does). On SIGTERM the worker stops taking runs and waits for the
step in flight.
"""

import argparse
import asyncio
import contextlib
import os
import signal
import socket
import sys
import uuid

import structlog

from app.workflows import config, definitions, engine, registry
from app.workflows.engine import SessionFactory

logger = structlog.get_logger()


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


async def run_one(factory: SessionFactory, who: str) -> bool:
    """Claim one due run and drive it as far as it goes. False when nothing was due."""
    claimed = await engine.claim(factory, who)
    if claimed is None:
        return False
    logger.info("workflow_run_claimed", run_id=str(claimed.id), workflow=claimed.workflow, status=claimed.status)
    outcome = await engine.drive(factory, claimed)
    logger.info("workflow_run_driven", run_id=str(claimed.id), workflow=claimed.workflow, outcome=outcome)
    return True


async def drain(factory: SessionFactory, who: str, limit: int = 10_000) -> int:
    done = 0
    while done < limit and await run_one(factory, who):
        done += 1
    return done


async def _slot(factory: SessionFactory, who: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            if await run_one(factory, who):
                continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the database may be briefly away: log the class, try again
            logger.error("workflow_worker_error", error=type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), config.poll_interval())


async def _purger(factory: SessionFactory, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with factory() as session:
                await engine.purge_finished(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("workflow_purge_error", error=type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), 3600.0)


async def run_forever(factory: SessionFactory, stop: asyncio.Event) -> None:
    who = worker_id()
    slots = config.concurrency(definitions.CONCURRENCY)
    logger.info("workflow_worker_started", concurrency=slots)
    tasks = [asyncio.create_task(_slot(factory, who, stop)) for _ in range(slots)]
    tasks.append(asyncio.create_task(_purger(factory, stop)))
    await asyncio.gather(*tasks)  # each ends when `stop` is set, after its current step
    logger.info("workflow_worker_stopped")


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.workflows.worker")
    parser.add_argument("--once", action="store_true", help="run what is due now, then exit")
    return parser.parse_args(argv)


async def _main(args: argparse.Namespace) -> None:
    from app.db import engine as db_engine
    from app.db import session_factory

    registry.load_handlers()  # a step without a function stops the worker here
    stop = asyncio.Event()
    try:
        if args.once:
            await drain(session_factory, worker_id())
            return
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_forever(session_factory, stop)
    finally:
        await db_engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main(_parse(sys.argv[1:])))
