"""Writing, purging and de-duplicating events (generated)."""

import datetime as _dt
import uuid
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import config
from app.events.models import DELIVERED, FAILED, PENDING, HandledEvent, OutboxEvent
from app.events.types import EVENT_TYPES
from app.models._base import utcnow


def _next_seq(aggregate_type: str, aggregate_id: uuid.UUID) -> sa.Select[Any]:
    # Callers hold the record's row lock (the write itself took it), so two writers of one record
    # cannot read the same maximum; the unique (type, id, seq) constraint is the backstop.
    return sa.select(sa.func.coalesce(sa.func.max(OutboxEvent.seq), 0) + 1).where(
        OutboxEvent.aggregate_type == aggregate_type, OutboxEvent.aggregate_id == aggregate_id
    )


def _row(
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    seq: int,
    payload: BaseModel,
    tenant_id: uuid.UUID | None,
) -> dict[str, Any]:
    model = EVENT_TYPES.get(event_type)
    if model is None or not isinstance(payload, model):
        raise ValueError(f"{event_type!r} needs a payload of its own type")  # fail closed
    now = utcnow()
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "seq": seq,
        "event_type": event_type,
        "payload": payload.model_dump(mode="json"),
        "created_at": now,
        "status": PENDING,
        "attempts": 0,
        "next_attempt_at": now,
    }
    row["tenant_id"] = tenant_id
    return row


async def add_event(
    session: AsyncSession,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    payload: BaseModel,
    tenant_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Add the event to the CALLER'S transaction: it commits or rolls back with the business write."""
    seq = (await session.execute(_next_seq(aggregate_type, aggregate_id))).scalar_one()
    row = _row(event_type, aggregate_type, aggregate_id, int(seq), payload, tenant_id)
    await session.execute(sa.insert(OutboxEvent).values(**row))
    return uuid.UUID(str(row["id"]))


def add_event_sync(
    connection: sa.Connection,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    payload: BaseModel,
    tenant_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """The same, for code running inside a flush (mapper events), on the flush's own connection."""
    seq = connection.execute(_next_seq(aggregate_type, aggregate_id)).scalar_one()
    row = _row(event_type, aggregate_type, aggregate_id, int(seq), payload, tenant_id)
    connection.execute(sa.insert(OutboxEvent).values(**row))
    return uuid.UUID(str(row["id"]))


async def already_handled(session: AsyncSession, event_id: uuid.UUID, consumer: str) -> bool:
    """True when `consumer` has handled `event_id` before; otherwise records it and returns False.

    Call it in the SAME transaction as the handler's own writes: the marker then commits with the work,
    and a failed handler (rolled back) can run again."""
    result = await session.execute(
        pg_insert(HandledEvent)
        .values(event_id=event_id, consumer=consumer, handled_at=utcnow())
        .on_conflict_do_nothing(index_elements=["event_id", "consumer"])
    )
    return bool(result.rowcount == 0)  # type: ignore[attr-defined]


async def purge_delivered(
    session: AsyncSession, retention_days: int | None = None, now: _dt.datetime | None = None
) -> int:
    """Delete delivered events older than the retention, and consumer markers older than TWICE the
    retention that no pending / failed event still needs. Failed events stay.

    A marker is the idempotency record of a delivery that may be retried (a parked event can be
    requeued long after it first ran), so it outlives the events it guards: it is dropped only when it
    is older than 2x the retention (far beyond the retry backoff, which is capped at minutes) and its
    event is delivered or already gone. Returns the number of events removed."""
    days = retention_days if retention_days is not None else config.retention_days()
    cutoff = (now or utcnow()) - _dt.timedelta(days=days)
    removed = await session.execute(
        sa.delete(OutboxEvent).where(
            OutboxEvent.status == DELIVERED, OutboxEvent.delivered_at < cutoff
        )
    )
    marker_cutoff = (now or utcnow()) - _dt.timedelta(days=2 * days)
    still_open = sa.select(OutboxEvent.id).where(
        OutboxEvent.id == HandledEvent.event_id, OutboxEvent.status != DELIVERED
    )
    await session.execute(
        sa.delete(HandledEvent).where(HandledEvent.handled_at < marker_cutoff, ~sa.exists(still_open))
    )
    await session.commit()
    return int(removed.rowcount or 0)  # type: ignore[attr-defined]


async def requeue_failed(session: AsyncSession, event_id: uuid.UUID | None = None) -> int:
    """Give parked (failed) events a fresh start: the owner's decision after fixing the cause."""
    stmt = (
        sa.update(OutboxEvent)
        .where(OutboxEvent.status == FAILED)
        .values(status=PENDING, attempts=0, next_attempt_at=utcnow(), last_error=None)
    )
    if event_id is not None:
        stmt = stmt.where(OutboxEvent.id == event_id)
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
