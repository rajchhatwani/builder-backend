"""Send the daily support-access digest. Run it from cron or a timer:

    python -m app.jobs.impersonation_digest            # send (once a day)
    python -m app.jobs.impersonation_digest --dry-run  # print it, send nothing
    python -m app.jobs.impersonation_digest --force    # send again

Exit status: 0 sent (or skipped as already sent / dry run), 1 not configured, 2 delivery
failed - so the scheduler's own alerting catches a broken job. Destinations:
BUILDER_SECURITY_DIGEST_WEBHOOK_URL and/or BUILDER_SECURITY_DIGEST_EMAIL (needs SMTP settings).
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.db import get_session_factory
from app.services import impersonation_digest


async def main(force: bool, dry_run: bool) -> int:
    settings = get_settings()
    async with get_session_factory()() as db:
        if dry_run:
            now = datetime.now(UTC)
            d = await impersonation_digest.build(
                db, now - timedelta(hours=settings.security_digest_hours), now
            )
            print(d.text)
            return 0
        result = await impersonation_digest.run(db, settings, force=force)
        await db.commit()
    if result.skipped:
        print(f"skipped: {result.skipped}")
        return 0
    if result.error == "no_destination":
        print("no destination: set BUILDER_SECURITY_DIGEST_WEBHOOK_URL or ..._EMAIL")
        return 1
    print(f"sent via {','.join(result.channels)}" if result.sent else f"failed: {result.error}")
    return 0 if result.sent and not result.error else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.force, args.dry_run)))
