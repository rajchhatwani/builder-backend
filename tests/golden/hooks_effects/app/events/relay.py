"""The relay: delivers outbox events to the adapter (generated).

    python -m app.events.relay          run until stopped (SIGTERM / Ctrl-C)
    python -m app.events.relay --once   deliver what is due, then exit

The API process also runs it unless EVENTS_RELAY_ENABLED=false. Any number of relays may run at once:
a row is claimed with FOR UPDATE SKIP LOCKED and stays locked until it is marked delivered, so no two
relays deliver one row at the same time; if a relay dies mid-delivery the row is simply claimed again
(at least once). An event is claimed only when every lower seq of its record is delivered.
"""

import asyncio
import contextlib
import datetime as _dt
import signal
import sys

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.events import adapters, bus, config, definitions
from app.events.models import DELIVERED, FAILED, PENDING, OutboxEvent
from app.events.outbox import purge_delivered
from app.models._base import utcnow

logger = structlog.get_logger()

SessionFactory = async_sessionmaker[AsyncSession]


def backoff_seconds(attempts: int) -> float:
    """Delay before the next try after `attempts` failures: 2, 4, 8 ... capped."""
    return float(min(config.BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), config.BACKOFF_CAP_SECONDS))


def _claim_statement(now: _dt.datetime) -> sa.Select[OutboxEvent]:
    earlier = aliased(OutboxEvent)
    blocked = (
        sa.select(sa.literal(1))
        .where(
            earlier.aggregate_type == OutboxEvent.aggregate_type,
            earlier.aggregate_id == OutboxEvent.aggregate_id,
            earlier.seq < OutboxEvent.seq,
            earlier.status != DELIVERED,
        )
        .exists()
    )
    return (
        sa.select(OutboxEvent)
        .where(OutboxEvent.status == PENDING, OutboxEvent.next_attempt_at <= now, ~blocked)
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(1)
        .with_for_update(skip_locked=True, of=OutboxEvent)
    )


def _describe(exc: Exception) -> str:
    """What is stored and shown about a failure: consumer names and error classes, never a payload.
    (A DeliveryFailed message is built from those only; any other exception text is not trusted.)"""
    if isinstance(exc, adapters.DeliveryFailed):
        return str(exc)[:500]
    return type(exc).__name__


def _envelope(row: OutboxEvent) -> bus.Event:
    return bus.Event(
        id=row.id,
        type=row.event_type,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        seq=row.seq,
        tenant_id=getattr(row, "tenant_id", None),
        occurred_at=row.created_at,
        payload=dict(row.payload),
    )


async def deliver_one(
    factory: SessionFactory, adapter: adapters.EventAdapter, max_attempts: int | None = None
) -> bool:
    """Claim and deliver one due event in its own transaction. False when nothing was due."""
    limit = max_attempts if max_attempts is not None else config.max_attempts()
    async with factory() as session:
        now = utcnow()
        row = (await session.scalars(_claim_statement(now))).first()
        if row is None:
            await session.rollback()
            return False
        try:
            await adapter.publish(_envelope(row))
        except Exception as exc:
            row.attempts += 1
            row.last_error = _describe(exc)
            if row.attempts >= limit:
                row.status = FAILED
                logger.error(
                    "event_dead_lettered",
                    event_id=str(row.id),
                    event_type=row.event_type,
                    attempts=row.attempts,
                )
            else:
                row.next_attempt_at = now + _dt.timedelta(seconds=backoff_seconds(row.attempts))
            await session.commit()
            return True
        row.status = DELIVERED
        row.delivered_at = utcnow()
        row.last_error = None
        await session.commit()
        return True


async def deliver_batch(
    factory: SessionFactory, adapter: adapters.EventAdapter, limit: int = 100
) -> int:
    done = 0
    while done < limit and await deliver_one(factory, adapter):
        done += 1
    return done


async def run_forever(
    factory: SessionFactory, adapter: adapters.EventAdapter, stop: asyncio.Event | None = None
) -> None:
    stop = stop or asyncio.Event()
    last_purge = 0.0
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        try:
            if await deliver_batch(factory, adapter):
                continue
            if loop.time() - last_purge >= config.PURGE_EVERY_SECONDS:
                last_purge = loop.time()
                async with factory() as session:
                    await purge_delivered(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the database may be briefly away: log the class, try again
            logger.error("event_relay_error", error=type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), config.poll_interval())


def start_relay() -> asyncio.Task[None] | None:
    """Start the relay inside the running app (None when EVENTS_RELAY_ENABLED=false)."""
    from app.db import session_factory

    bus.load_subscribers()
    if not config.relay_enabled():
        logger.info("event_relay_disabled")
        return None
    adapter = adapters.make_adapter(definitions.ADAPTER)
    return asyncio.create_task(run_forever(session_factory, adapter), name="event-relay")


async def stop_relay(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _main(once: bool) -> None:
    from app.db import engine, session_factory

    bus.load_subscribers()
    adapter = adapters.make_adapter(definitions.ADAPTER)
    stop = asyncio.Event()
    try:
        if once:
            await deliver_batch(session_factory, adapter, limit=10_000)
            return
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_forever(session_factory, adapter, stop)
    finally:
        await adapter.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main("--once" in sys.argv[1:]))
