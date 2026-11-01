"""Delete change-history rows older than their entity's retention (generated).

    python -m app.change_history.purge

Run it from a scheduler (cron, a Kubernetes CronJob). Rows of an entity that has no history config any
more are left alone. Prints one line per entity: how many rows went."""

import asyncio
import datetime as _dt

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.change_history.definitions import HISTORY
from app.change_history.models import Change


async def purge(session: AsyncSession, now: _dt.datetime | None = None) -> dict[str, int]:
    """Remove the expired rows (one transaction); returns the number removed per entity."""
    moment = now or _dt.datetime.now(_dt.UTC)
    removed: dict[str, int] = {}
    for entity, config in sorted(HISTORY.items()):
        cutoff = moment - _dt.timedelta(days=config["retention_days"])
        result = await session.execute(
            sa.delete(Change).where(Change.entity == entity, Change.created_at < cutoff)
        )
        removed[entity] = int(result.rowcount or 0)  # type: ignore[attr-defined]
    await session.commit()
    return removed


async def _main() -> None:
    from app.db import engine, session_factory

    try:
        async with session_factory() as session:
            for entity, count in (await purge(session)).items():
                print(f"{entity}: {count} expired rows removed")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
