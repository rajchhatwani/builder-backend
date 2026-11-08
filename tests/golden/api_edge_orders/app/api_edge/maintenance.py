"""Housekeeping for the API edge tables (generated). Run it from a schedule:

    python -m app.api_edge.maintenance

Deletes expired idempotency keys, idle rate-limit buckets and old quota periods."""

import asyncio

from app.api_edge import idempotency, quota, ratelimit
from app.db import engine, session_factory


async def purge() -> dict[str, int]:
    done: dict[str, int] = {}
    async with session_factory() as session:
        done["idempotency"] = await idempotency.purge(session)
        await session.commit()
    done["rate_buckets"] = await ratelimit.purge()
    done["quota_usage"] = await quota.purge()
    return done


async def main() -> None:
    try:
        print(await purge())  # noqa: T201
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
