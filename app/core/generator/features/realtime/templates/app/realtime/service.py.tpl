"""The realtime event log (generated): publish inside the caller's transaction, read for the stream, prune.

Transport: the stream polls this table (a short session per poll) instead of LISTEN/NOTIFY, so it needs no
long-lived database connection per stream and works through any pooler. Latency is the poll interval.

Ordering: `publish` takes one advisory TRANSACTION lock before the insert allocates its id, so ids are
committed in id order. A reader that has seen id N never misses a smaller id that commits later (no gaps),
and replay by `id > last` has no duplicates. The lock is held until the write commits: realtime-tracked
writes are serialised with each other (and only with each other)."""

import datetime as _dt
import itertools
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import utcnow
from app.realtime import protocol
from app.realtime.models import RealtimeEvent, RealtimeFloor

PRUNE_EVERY = 100
_LOCK_KEY = "app.realtime"
_writes = itertools.count(1)


async def publish(
    session: AsyncSession,
    entity: str,
    record_id: uuid.UUID,
    op: str,
    *,
    tenant_id: uuid.UUID | None = None,
    created_by_id: uuid.UUID | None = None,
) -> None:
    """Insert one event row in the CALLER'S transaction (visible to streams when it commits)."""
    await session.execute(sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": _LOCK_KEY})
    await session.execute(
        sa.insert(RealtimeEvent).values(
            entity=entity,
            record_id=record_id,
            op=op,
            tenant_id=tenant_id,
            created_by_id=created_by_id,
            created_at=utcnow(),
        )
    )
    if next(_writes) % PRUNE_EVERY == 0:  # job-less retention: every 100th write in this process
        await prune(session)


async def prune(
    session: AsyncSession,
    *,
    max_age: _dt.timedelta = _dt.timedelta(hours=protocol.RETENTION_HOURS),
    keep: int = protocol.RETENTION_MAX_EVENTS,
    now: _dt.datetime | None = None,
) -> int:
    """Delete events older than `max_age` or beyond the newest `keep`; remember the highest deleted id as
    the floor. Returns how many rows went."""
    cutoff_time = (now or utcnow()) - max_age
    cutoff_id = (
        await session.execute(
            sa.select(RealtimeEvent.id).order_by(RealtimeEvent.id.desc()).offset(keep).limit(1)
        )
    ).scalar_one_or_none()
    result = await session.execute(
        sa.text(
            "WITH d AS (DELETE FROM rt_events WHERE created_at < :t OR id <= :i RETURNING id) "
            "SELECT count(*), max(id) FROM d"
        ),
        {"t": cutoff_time, "i": cutoff_id if cutoff_id is not None else -1},
    )
    count, top = result.one()
    if count:
        floor = await session.get(RealtimeFloor, 1, with_for_update=True)
        if floor is None:
            session.add(RealtimeFloor(id=1, floor_id=int(top)))
        else:
            floor.floor_id = max(floor.floor_id, int(top))
        await session.flush()
    return int(count)


async def floor_and_head(session: AsyncSession) -> tuple[int, int]:
    floor = (await session.execute(sa.select(RealtimeFloor.floor_id).where(RealtimeFloor.id == 1))).scalar_one_or_none()
    head = (
        await session.execute(sa.select(RealtimeEvent.id).order_by(RealtimeEvent.id.desc()).limit(1))
    ).scalar_one_or_none()
    return int(floor or 0), int(head or 0)


async def events_after(session: AsyncSession, last_id: int, limit: int = 200) -> list[RealtimeEvent]:
    rows = (
        await session.execute(
            sa.select(RealtimeEvent).where(RealtimeEvent.id > last_id).order_by(RealtimeEvent.id).limit(limit)
        )
    ).scalars()
    return list(rows)


def visible(row: RealtimeEvent, rules: dict[str, dict[str, Any]]) -> bool:
    """May this caller see the event? `rules` maps an entity to the row scope of the caller's `list`
    (column -> required value). Fail closed: an entity without a rule, or a scope column the event does not
    carry (anything but created_by_id / tenant_id), delivers nothing."""
    scope = rules.get(row.entity)
    if scope is None:
        return False
    for column, wanted in scope.items():
        if column == "created_by_id":
            if row.created_by_id != wanted:
                return False
        elif column == "tenant_id":
            if row.tenant_id != wanted:
                return False
        else:
            return False
    return True


def to_event(row: RealtimeEvent) -> protocol.Event:
    return protocol.Event(
        topic=row.entity,
        type=f"{row.entity}.{row.op}",
        data={"entity": row.entity, "record_id": str(row.record_id), "op": row.op},
        at=row.created_at,
        id=row.id,
    )
