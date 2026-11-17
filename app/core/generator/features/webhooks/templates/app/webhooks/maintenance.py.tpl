"""Housekeeping (generated): `python -m app.webhooks.maintenance` (run `make webhooks-maintenance` daily).

Deletes finished deliveries (and their attempts) older than WEBHOOKS_LOG_RETENTION_DAYS (default 30) and incoming
delivery ids older than their endpoint's `dedupe_days` (always far longer than the replay tolerance)."""

import asyncio
import datetime as _dt
import os

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import utcnow
from app.webhooks import definitions
from app.webhooks.models import Delivery, InboundSeen


def _retention_days() -> int:
    raw = os.environ.get("WEBHOOKS_LOG_RETENTION_DAYS", "30").strip() or "30"
    try:
        return max(int(raw), 1)
    except ValueError:
        raise RuntimeError(f"WEBHOOKS_LOG_RETENTION_DAYS must be a whole number of days, got {raw!r}") from None


async def purge(session: AsyncSession, now: _dt.datetime | None = None) -> tuple[int, int]:
    stamp = now or utcnow()
    days = _retention_days()
    deliveries = await session.execute(
        sa.delete(Delivery).where(Delivery.finished_at.is_not(None), Delivery.finished_at < stamp - _dt.timedelta(days=days))
    )
    seen = 0
    for name, cfg in definitions.INBOUND.items():
        cutoff = stamp - _dt.timedelta(days=cfg["dedupe_days"])
        result = await session.execute(sa.delete(InboundSeen).where(InboundSeen.endpoint == name, InboundSeen.received_at < cutoff))
        seen += int(result.rowcount or 0)  # type: ignore[attr-defined]
    await session.commit()
    return int(deliveries.rowcount or 0), seen  # type: ignore[attr-defined]


async def _main() -> None:
    from app.db import engine, session_factory

    try:
        async with session_factory() as session:
            removed = await purge(session)
        print(f"removed {removed[0]} deliveries and {removed[1]} incoming ids")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
