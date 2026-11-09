"""Fire due scheduled reports. Run it from cron or a timer, every minute:

    python -m app.jobs.report_scheduler

Each enabled report stores its latest due slot exactly once, however many copies of this job run
at the same time or how often it is called. After downtime only the latest missed slot fires.
Exit status: 0 ok (prints how many runs were stored), 2 failed.
"""

import asyncio
from datetime import UTC, datetime

from app.db import get_session_factory
from app.services.metrics_service import fire_due_reports


async def main() -> int:
    async with get_session_factory()() as db:
        try:
            fired = await fire_due_reports(db, datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001 - the exit code is the alert
            print(f"failed: {type(exc).__name__}")
            return 2
    print(f"fired {fired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
