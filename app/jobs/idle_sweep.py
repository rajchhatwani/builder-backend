"""Discard idle workspaces and repair usage gauges. One-shot by default (cron or a timer), or a loop:

    python -m app.jobs.idle_sweep                 # one sweep, then exit
    python -m app.jobs.idle_sweep --interval 3600 # sweep every hour (use app.jobs.scheduler to
                                                  # run it next to the report scheduler)

A sweep runs `expire_idle_workspaces` (every live workspace untouched for `workspace_idle_ttl_days`
goes through the normal discard path, which releases the org's `workspaces.active` gauge) and then
`reconcile_gauges`, which recomputes every gauge from its source rows so drift left by cascade
deletes or a crashed worker heals. It is idempotent: a second run right after finds nothing.
Exit status: 0 ok (prints how many workspaces were discarded), 2 failed.
"""

import argparse
import asyncio
from datetime import datetime

from app.db import get_session_factory
from app.services.usage_service import reconcile_gauges
from app.services.workspace_service import expire_idle_workspaces


async def sweep(now: datetime | None = None) -> tuple[int, int]:
    """One sweep; returns (workspaces discarded, gauge rows corrected)."""
    async with get_session_factory()() as db:
        done = await expire_idle_workspaces(db, now)
        fixed = await reconcile_gauges(db)
        await db.commit()
    return len(done), fixed


async def main(interval: int | None = None) -> int:
    while True:
        try:
            discarded, fixed = await sweep()
        except Exception as exc:  # noqa: BLE001 - the exit code is the alert
            print(f"failed: {type(exc).__name__}")
            if interval is None:
                return 2
        else:
            print(f"discarded {discarded}, gauges fixed {fixed}")
        if interval is None:
            return 0
        await asyncio.sleep(interval)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=None, help="seconds between sweeps; omit for one shot")
    raise SystemExit(asyncio.run(main(ap.parse_args().interval)))
