"""One process for every periodic operator job:

    python -m app.jobs.scheduler

Runs the report scheduler every minute and the idle-workspace sweep + gauge reconcile every hour
(both are idempotent and safe to run in several copies). A failing job is logged and retried on
its next tick; it never stops the others. Intervals: BUILDER_SCHEDULER_REPORT_SECONDS (60) and
BUILDER_SCHEDULER_SWEEP_SECONDS (3600).
"""

import asyncio
import os
from collections.abc import Awaitable, Callable

from app.jobs import idle_sweep, report_scheduler

Job = Callable[[], Awaitable[int]]


def jobs() -> list[tuple[str, Job, int]]:
    return [
        ("reports", report_scheduler.main, max(5, int(os.environ.get("BUILDER_SCHEDULER_REPORT_SECONDS", "60")))),
        ("idle_sweep", idle_sweep.main, max(5, int(os.environ.get("BUILDER_SCHEDULER_SWEEP_SECONDS", "3600")))),
    ]


async def _loop(name: str, job: Job, every: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            code = await job()
            if code:
                print(f"{name}: exit {code}")
        except Exception as exc:  # noqa: BLE001 - keep the other jobs alive
            print(f"{name}: crashed {type(exc).__name__}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=every)
        except TimeoutError:
            pass


async def run(stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    await asyncio.gather(*(_loop(n, j, e, stop) for n, j, e in jobs()))


if __name__ == "__main__":
    asyncio.run(run())
