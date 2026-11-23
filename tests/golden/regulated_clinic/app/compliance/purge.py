"""Run the retention rules from a scheduler (generated).

    python -m app.compliance.purge [--dry-run]

Purges or anonymises the rows older than their rule's retention, except rows under an active legal hold (those are
skipped and counted as `held`). Prints one line per rule; every run is audited."""

import asyncio
import sys


async def _main(dry_run: bool) -> None:
    from app.compliance import service
    from app.db import engine, session_factory

    try:
        async with session_factory() as session:
            summary = await service.run_retention(session, "cli", dry_run=dry_run)
        for rule in summary["rules"]:
            print(
                f"{rule['entity']} ({rule['action']}): {rule['processed']} {'would be ' if dry_run else ''}processed, "
                f"{rule['held']} held, {rule['blocked']} blocked"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main("--dry-run" in sys.argv[1:]))
