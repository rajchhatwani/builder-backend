"""Realtime event log (B4-2, C18): publish into the caller's transaction, read for the stream.

Transport choice: the stream polls this table every 0.5 s (a short session per poll) instead of
LISTEN/NOTIFY. It needs no dedicated long-lived connection per stream, works through any pooler,
and the table is the single source of truth for replay. Latency is bounded by the poll interval.

Ordering: `publish` takes a per-project advisory transaction lock BEFORE the insert allocates its
id, so for one project ids are committed in id order. A reader that has seen id N therefore never
misses a smaller id of that project that commits later (no gaps), and replay by `id > last` has
no duplicates.
"""

import random
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import realtime as rt
from app.models.mixins import _utcnow
from app.models.realtime import RealtimeEvent, RealtimeFloor

PRUNE_EVERY = 100


def to_event(row: RealtimeEvent) -> rt.Event:
    return rt.Event(
        project_id=str(row.project_id),
        topic=row.topic,
        type=row.type,
        data=row.data,
        at=row.created_at,
        id=row.id,
    )


async def publish(
    session: AsyncSession, project_id: uuid.UUID, topic: str, type_: str, data: dict[str, Any]
) -> int:
    """Insert one event in the CALLER'S transaction (visible to streams when it commits).
    `data` carries ids, counts and names only: never secrets or raw row data."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"rt:{project_id}"}
    )
    row = RealtimeEvent(project_id=project_id, topic=topic, type=type_, data=data)
    session.add(row)
    await session.flush()
    if random.randrange(PRUNE_EVERY) == 0:  # per project, not by global id (some projects would never prune)
        await prune_events(session, project_id)
    return row.id


async def prune_events(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    max_age: timedelta = timedelta(hours=rt.RETENTION_HOURS),
    keep: int = rt.RETENTION_MAX_EVENTS,
    now: datetime | None = None,
) -> int:
    """Delete events older than `max_age` or beyond the newest `keep`; remember the highest
    deleted id as the project's floor. Returns how many rows went."""
    cutoff_time = (now or _utcnow()) - max_age
    cutoff_id = (
        await session.execute(
            select(RealtimeEvent.id)
            .where(RealtimeEvent.project_id == project_id)
            .order_by(RealtimeEvent.id.desc())
            .offset(keep)
            .limit(1)
        )
    ).scalar_one_or_none()
    result = await session.execute(
        text(
            "WITH d AS (DELETE FROM realtime_events WHERE project_id = :p "
            "AND (created_at < :t OR id <= :i) RETURNING id) "
            "SELECT count(*), max(id) FROM d"
        ),
        {"p": project_id, "t": cutoff_time, "i": cutoff_id if cutoff_id is not None else -1},
    )
    count, top = result.one()
    if count:
        floor = await session.get(RealtimeFloor, project_id, with_for_update=True)
        if floor is None:
            session.add(RealtimeFloor(project_id=project_id, floor_id=int(top)))
        else:
            floor.floor_id = max(floor.floor_id, int(top))
        await session.flush()
    return int(count)


async def floor_and_head(session: AsyncSession, project_id: uuid.UUID) -> tuple[int, int]:
    floor = (
        await session.execute(
            select(RealtimeFloor.floor_id).where(RealtimeFloor.project_id == project_id)
        )
    ).scalar_one_or_none()
    head = (
        await session.execute(
            select(RealtimeEvent.id)
            .where(RealtimeEvent.project_id == project_id)
            .order_by(RealtimeEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return int(floor or 0), int(head or 0)


async def events_after(
    session: AsyncSession, project_id: uuid.UUID, last_id: int, limit: int = 200
) -> list[rt.Event]:
    rows = (
        await session.execute(
            select(RealtimeEvent)
            .where(RealtimeEvent.project_id == project_id, RealtimeEvent.id > last_id)
            .order_by(RealtimeEvent.id)
            .limit(limit)
        )
    ).scalars()
    return [to_event(r) for r in rows]
