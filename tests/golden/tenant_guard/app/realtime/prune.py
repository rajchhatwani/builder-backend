"""Retention for the realtime event log: `python -m app.realtime.prune` (events older than 24 h or beyond the
newest 10 000 go). The write path also prunes on its own every 100th write, so a scheduler is optional."""

import asyncio

from app.db import session_factory
from app.realtime import service


async def main() -> int:
    async with session_factory() as session:
        removed = await service.prune(session)
        await session.commit()
    return removed


if __name__ == "__main__":
    print(f"pruned {asyncio.run(main())} realtime events")
