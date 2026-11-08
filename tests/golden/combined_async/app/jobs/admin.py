"""Look at and requeue dead jobs (generated).

    python -m app.jobs.admin list-dead             what failed for good (never prints a payload)
    python -m app.jobs.admin requeue [JOB_ID]      give one dead job (or all) a fresh set of attempts
"""

import argparse
import asyncio
import sys
import uuid

from app.jobs import queue


async def _main(args: argparse.Namespace) -> None:
    from app.db import engine, session_factory

    try:
        async with session_factory() as session:
            if args.command == "list-dead":
                for job in await queue.list_dead(session):
                    print(job.id, job.name, f"attempts={job.attempts}", f"error={job.last_error}", job.finished_at)
            else:
                job_id = uuid.UUID(args.job_id) if args.job_id else None
                count = await queue.requeue_dead(session, job_id)
                await session.commit()
                print(f"requeued {count}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m app.jobs.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-dead")
    requeue = sub.add_parser("requeue")
    requeue.add_argument("job_id", nargs="?")
    asyncio.run(_main(parser.parse_args(sys.argv[1:])))
