"""The dispatcher (generated): sends queued messages through app.providers, with retries and backoff.

A row is claimed with FOR UPDATE SKIP LOCKED under a lease (several dispatchers may run), the provider is
called OUTSIDE any transaction, and the outcome is written with a conditional UPDATE that only matches
while the lease is still ours. A retryable failure (network, rate limit, open breaker) requeues the row
with exponential backoff until `MAX_ATTEMPTS`; anything else fails it at once. When a row ends (sent,
failed, suppressed) its address and variables are erased. Only the error CODE is stored, never a message.

    python -m app.notifications.dispatcher [--once]
"""

import asyncio
import contextlib
import datetime as _dt
import signal
import sys
import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models._base import utcnow
from app.notifications import config, definitions, render, service
from app.notifications.models import (
    FAILED,
    PROCESSING,
    QUEUED,
    SENT,
    SUPPRESSED,
    NotificationDelivery,
)
from app.providers import client as provider_client
from app.providers.errors import CircuitOpen, ProviderError
from app.providers.schemas import EmailRequest, PushRequest, SmsRequest

logger = structlog.get_logger("notifications")
SessionFactory = async_sessionmaker[AsyncSession]
_MAX_BACKOFF = 3600.0


@dataclass(frozen=True)
class Claimed:
    id: uuid.UUID
    tenant_id: uuid.UUID
    type: str
    channel: str
    recipient_key: str
    address: str | None
    variables: dict[str, Any]
    attempt: int
    token: uuid.UUID


def backoff(attempt: int) -> float:
    return min(float(definitions.BACKOFF_SECONDS) * 2 ** max(attempt - 1, 0), _MAX_BACKOFF)


async def claim(factory: SessionFactory, *, now: _dt.datetime | None = None) -> Claimed | None:
    stamp = now or utcnow()
    async with factory() as session:
        due = sa.or_(
            sa.and_(NotificationDelivery.status == QUEUED, NotificationDelivery.next_attempt_at <= stamp),
            sa.and_(NotificationDelivery.status == PROCESSING, NotificationDelivery.lease_expires_at <= stamp),
        )
        row = (
            await session.scalars(
                sa.select(NotificationDelivery).where(due).order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
                .limit(1).with_for_update(skip_locked=True)
            )
        ).first()
        if row is None:
            await session.rollback()
            return None
        if row.attempts >= definitions.MAX_ATTEMPTS:
            # claimed MAX times and never finished (the worker keeps dying mid-send): stop re-sending
            row.status = FAILED
            row.error_code = "abandoned"
            row.address = None
            row.variables = None
            row.lease_token = None
            row.lease_expires_at = None
            row.finished_at = stamp
            logger.error("notification_abandoned", id=str(row.id), attempts=row.attempts)
            await session.commit()
            return await claim(factory, now=now)
        token = uuid.uuid4()
        row.status = PROCESSING
        row.attempts += 1
        row.lease_token = token
        row.lease_expires_at = stamp + _dt.timedelta(seconds=config.lease_seconds())
        claimed = Claimed(
            row.id, row.tenant_id, row.type, row.channel, row.recipient_key, row.address,
            dict(row.variables or {}), row.attempts, token,
        )
        await session.commit()
        return claimed


async def _finish(factory: SessionFactory, job: Claimed, status: str, **values: Any) -> bool:
    """Write the outcome only if the lease is still ours. Terminal states erase address and variables."""
    changes: dict[str, Any] = {"status": status, "lease_token": None, "lease_expires_at": None, **values}
    if status != QUEUED:
        changes.update(address=None, variables=None, finished_at=utcnow())
    async with factory() as session:
        won = (
            await session.execute(
                sa.update(NotificationDelivery)
                .where(
                    NotificationDelivery.id == job.id,
                    NotificationDelivery.lease_token == job.token,
                    NotificationDelivery.status == PROCESSING,
                )
                .values(**changes)
                .returning(NotificationDelivery.id)
            )
        ).scalar_one_or_none()
        await session.commit()
    if won is None:
        logger.warning("notification_lease_lost", id=str(job.id))
    return won is not None


def _request(channel: str, address: str, subject: str, body: str) -> EmailRequest | SmsRequest | PushRequest:
    if channel == "email":
        return EmailRequest(to=address, subject=subject, body=body)
    if channel == "sms":
        return SmsRequest(to=address, body=body)
    return PushRequest(device=address, title=subject, body=body)


async def process(factory: SessionFactory, job: Claimed) -> str:
    """Send one claimed message. Returns sent | retry | failed | suppressed | lost."""
    try:
        async with factory() as session:
            # honour an opt-out made after the message was queued (fail closed: an error below fails it)
            if job.address is None or not await service.preference(session, job.tenant_id, job.recipient_key, job.type, job.channel):
                reason = "no_address" if job.address is None else "opt_out"
                ok = await _finish(factory, job, SUPPRESSED, reason=reason)
                return "suppressed" if ok else "lost"
            tpl = await service.effective_template(session, job.tenant_id, job.type, job.channel)
            subject, body = service.render_template(tpl, job.variables)
            request = _request(job.channel, job.address, subject, body)
            adapter, _ = await provider_client.resolve(session, job.tenant_id, job.channel)
            provider = adapter.name
            result = await provider_client.call_provider(session, job.tenant_id, job.channel, request, prefer=None)
            message_id = str(getattr(result, "message_id", ""))[:200]
    except render.RenderError:
        ok = await _finish(factory, job, FAILED, error_code="render_error")
        return "failed" if ok else "lost"
    except ProviderError as exc:
        code = str(exc.code)[:40]
        # a paused provider (open breaker) is a wait, not a refusal
        if (exc.retryable or isinstance(exc, CircuitOpen)) and job.attempt < definitions.MAX_ATTEMPTS:
            when = utcnow() + _dt.timedelta(seconds=backoff(job.attempt))
            ok = await _finish(factory, job, QUEUED, error_code=code, next_attempt_at=when)
            return "retry" if ok else "lost"
        ok = await _finish(factory, job, FAILED, error_code=code)
        return "failed" if ok else "lost"
    except Exception as exc:  # noqa: BLE001 - class only: a message may carry an address or a value
        logger.error("notification_error", id=str(job.id), error_class=type(exc).__name__)
        if job.attempt < definitions.MAX_ATTEMPTS:
            when = utcnow() + _dt.timedelta(seconds=backoff(job.attempt))
            ok = await _finish(factory, job, QUEUED, error_code="internal_error", next_attempt_at=when)
            return "retry" if ok else "lost"
        ok = await _finish(factory, job, FAILED, error_code="internal_error")
        return "failed" if ok else "lost"
    ok = await _finish(factory, job, SENT, provider=provider, provider_message_id=message_id, error_code=None, reason=None)
    logger.info("notification_sent", id=str(job.id), type=job.type, channel=job.channel, provider=provider)
    return "sent" if ok else "lost"


async def deliver_batch(factory: SessionFactory, limit: int = config.BATCH) -> int:
    done = 0
    while done < limit:
        job = await claim(factory)
        if job is None:
            break
        await process(factory, job)
        done += 1
    return done


async def purge(session: AsyncSession, *, now: _dt.datetime | None = None) -> int:
    cutoff = (now or utcnow()) - _dt.timedelta(days=definitions.RETENTION_DAYS)
    result = await session.execute(
        sa.delete(NotificationDelivery).where(
            NotificationDelivery.status.in_([SENT, FAILED, SUPPRESSED]), NotificationDelivery.finished_at < cutoff
        )
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def run_forever(factory: SessionFactory, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    last_purge = 0.0
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        try:
            if await deliver_batch(factory):
                continue
            if loop.time() - last_purge >= config.PURGE_EVERY_SECONDS:
                last_purge = loop.time()
                async with factory() as session:
                    await purge(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the database may be briefly away
            logger.error("notification_dispatcher_error", error=type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), config.poll_seconds())


def start_dispatcher() -> asyncio.Task[None] | None:
    """Start sending inside the running app (None when NOTIFICATIONS_DISPATCHER_ENABLED=false)."""
    from app.db import session_factory

    if not config.dispatcher_enabled():
        logger.info("notification_dispatcher_disabled")
        return None
    return asyncio.create_task(run_forever(session_factory), name="notification-dispatcher")


async def stop_dispatcher(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _main(once: bool) -> None:
    from app.db import engine, session_factory

    stop = asyncio.Event()
    try:
        if once:
            await deliver_batch(session_factory, limit=10_000)
            return
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_forever(session_factory, stop)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main("--once" in sys.argv[1:]))
