"""Reconciliation (generated): make our records agree with the provider's, and repair what a crash
or a lost webhook left behind.

Runs as a periodic job on the workers, and can be run by hand or from cron:

    python -m app.payments.reconcile

It is safe to run at any time and from several places at once: every repair is the same guarded,
idempotent operation the normal flow uses. Anything it cannot repair is written to the audit log.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
import structlog

from app.core.errors import AppError
from app.db import engine, session_factory
from app.payments import audit, config, events, jobs, service, state
from app.payments.models import Payment, Refund, WebhookEvent
from app.payments.providers import get_provider
from app.payments.providers.base import ProviderError

logger = structlog.get_logger()

_BATCH = 100
_RECHECK_WINDOW = timedelta(days=30)


async def run() -> dict[str, int]:
    """One reconciliation pass. Returns how many items of each kind were looked at."""
    now = datetime.now(UTC)
    counts = {"payments": 0, "refunds": 0, "events": 0, "errors": 0}
    await _stuck_payments(now, counts)
    await _open_payments(now, counts)
    await _recheck_succeeded(now, counts)
    await _refunds(now, counts)
    await _events(now, counts)
    logger.info("reconcile_done", **counts)
    return counts


async def _ids(statement: sa.Select[tuple[uuid.UUID]]) -> list[uuid.UUID]:
    async with session_factory() as session:
        return list((await session.execute(statement)).scalars())


async def _stuck_payments(now: datetime, counts: dict[str, int]) -> None:
    """Payments that never got their checkout (a crash, or the provider was down)."""
    ids = await _ids(
        sa.select(Payment.id)
        .where(Payment.status == state.CREATING, Payment.created_at < now - timedelta(seconds=30))
        .order_by(Payment.created_at)
        .limit(_BATCH)
    )
    for payment_id in ids:
        counts["payments"] += 1
        async with session_factory() as session:
            try:
                await service.finish_payment(session, payment_id)
            except (AppError, ProviderError):
                await session.rollback()  # unavailable: it will be tried again next pass


async def _open_payments(now: datetime, counts: dict[str, int]) -> None:
    """Checkouts we are waiting on whose webhook may have been lost."""
    ids = await _ids(
        sa.select(Payment.id)
        .where(
            Payment.status.in_((state.REQUIRES_PAYMENT, state.PROCESSING)),
            Payment.provider_session_id.is_not(None),
            Payment.updated_at < now - timedelta(minutes=3),
            sa.or_(Payment.last_synced_at.is_(None), Payment.last_synced_at < now - timedelta(minutes=3)),
        )
        .order_by(Payment.updated_at)
        .limit(_BATCH)
    )
    await _sync(ids, counts)


async def _recheck_succeeded(now: datetime, counts: dict[str, int]) -> None:
    """Completed payments are re-read now and then; any difference is recorded, not hidden."""
    ids = await _ids(
        sa.select(Payment.id)
        .where(
            Payment.status == state.SUCCEEDED,
            Payment.created_at > now - _RECHECK_WINDOW,
            Payment.provider_session_id.is_not(None),
            sa.or_(Payment.last_synced_at.is_(None), Payment.last_synced_at < now - timedelta(hours=6)),
        )
        .order_by(Payment.last_synced_at.nulls_first())
        .limit(_BATCH)
    )
    await _sync(ids, counts)


async def _sync(ids: list[uuid.UUID], counts: dict[str, int]) -> None:
    provider = get_provider()
    for payment_id in ids:
        counts["payments"] += 1
        async with session_factory() as session:
            try:
                payment = await session.get(Payment, payment_id)
                if payment is None or payment.provider_session_id is None:
                    continue
                checkout = await provider.retrieve_checkout(payment.provider_session_id)
                await service.sync_payment_from_checkout(
                    session, payment_id, checkout, actor_type=audit.ACTOR_SYSTEM
                )
                if payment.provider_payment_intent_id and payment.status == state.SUCCEEDED:
                    for reported in await provider.list_refunds(payment.provider_payment_intent_id):
                        await service.apply_provider_refund(session, payment_id, reported)
            except ProviderError as exc:
                counts["errors"] += 1
                await session.rollback()
                logger.warning("reconcile_provider_error", payment_id=str(payment_id), code=exc.code)


async def _refunds(now: datetime, counts: dict[str, int]) -> None:
    waiting = await _ids(
        sa.select(Refund.id)
        .where(
            sa.or_(
                sa.and_(Refund.status == state.REQUESTED, Refund.updated_at < now - timedelta(seconds=45)),
                sa.and_(Refund.status == state.SUBMITTING, Refund.locked_until < now),
            )
        )
        .limit(_BATCH)
    )
    for refund_id in waiting:
        counts["refunds"] += 1
        async with session_factory() as session:
            try:
                await service.dispatch_refund(session, refund_id)
            except (AppError, ProviderError):
                await session.rollback()
    pending = await _ids(
        sa.select(Refund.id)
        .where(
            Refund.status == state.PENDING,
            Refund.provider_refund_id.is_not(None),
            Refund.updated_at < now - timedelta(minutes=10),
        )
        .limit(_BATCH)
    )
    provider = get_provider()
    for refund_id in pending:
        counts["refunds"] += 1
        async with session_factory() as session:
            try:
                refund = await session.get(Refund, refund_id)
                if refund is None or refund.provider_refund_id is None:
                    continue
                reported = await provider.retrieve_refund(refund.provider_refund_id)
                await service.apply_provider_refund(session, refund.payment_id, reported)
            except ProviderError:
                counts["errors"] += 1
                await session.rollback()


async def _events(now: datetime, counts: dict[str, int]) -> None:
    """Stored events nobody has processed (a crash between storing and handling)."""
    ids = await _ids(
        sa.select(WebhookEvent.id)
        .where(
            sa.or_(
                sa.and_(
                    WebhookEvent.status.in_((events.RECEIVED, events.FAILED)),
                    WebhookEvent.received_at < now - timedelta(minutes=2),
                ),
                sa.and_(WebhookEvent.status == events.PROCESSING, WebhookEvent.locked_until < now),
            )
        )
        .order_by(WebhookEvent.received_at)
        .limit(_BATCH)
    )
    bucket = int(now.timestamp() // 600)
    async with session_factory() as session:
        for event_id in ids:
            counts["events"] += 1
            await jobs.enqueue(
                session,
                jobs.PROCESS_EVENT,
                {"event_id": str(event_id)},
                dedupe_key=f"event:{event_id}:{bucket}",
            )
        await session.commit()


async def main() -> None:
    config.get_payments_settings().check()
    try:
        print(await run())  # noqa: T201 - command line output
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
