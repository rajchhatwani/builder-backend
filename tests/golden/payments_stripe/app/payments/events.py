"""Provider webhook events (generated): store once, process exactly once in effect.

Receiving is separated from processing. `store_event` records a verified event (a unique index on
provider + event id makes duplicates and replays harmless). `process_event` claims the stored event,
asks the provider for the current state of the object it names, and applies that. A webhook is a
hint, never the truth: an event that is old, duplicated or out of order cannot move a payment to a
state the provider no longer reports.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments import config, service
from app.payments.models import Payment, WebhookEvent
from app.payments.providers import get_provider
from app.payments.providers.base import ProviderEvent, ProviderRejected, ProviderUnavailable

logger = structlog.get_logger()

RECEIVED = "received"
PROCESSING = "processing"
PROCESSED = "processed"
IGNORED = "ignored"
FAILED = "failed"

_MAX_UNKNOWN_ATTEMPTS = 4


class EventRetry(Exception):
    """Processing could not finish now; try the same event again later."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def store_event(
    session: AsyncSession, provider: str, event: ProviderEvent, raw_body: bytes
) -> tuple[uuid.UUID, bool]:
    """Save a verified event. Returns (row id, True if it is new, False for a duplicate)."""
    row = (
        await session.execute(
            insert(WebhookEvent)
            .values(
                id=uuid.uuid4(),
                provider=provider,
                event_id=event.event_id,
                event_type=event.type,
                livemode=event.livemode,
                status=RECEIVED,
                attempts=0,
                payload=event.reduced,
                payload_sha256=hashlib.sha256(raw_body).hexdigest(),
                provider_created_at=event.created,
                received_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(constraint="uq_pay_webhook_events_provider_event")
            .returning(WebhookEvent.id)
        )
    ).first()
    if row is not None:
        return row[0], True
    existing = (
        await session.execute(
            sa.select(WebhookEvent.id).where(
                WebhookEvent.provider == provider, WebhookEvent.event_id == event.event_id
            )
        )
    ).scalar_one()
    return existing, False


async def event_status(session: AsyncSession, event_pk: uuid.UUID) -> str:
    return (
        await session.execute(sa.select(WebhookEvent.status).where(WebhookEvent.id == event_pk))
    ).scalar_one()


async def process_event(session: AsyncSession, event_pk: uuid.UUID) -> None:
    """Handle one stored event. A no-op if another process already has it or it is finished."""
    claimed = (
        await session.execute(
            sa.text(
                """
                UPDATE pay_webhook_events SET status = 'processing', attempts = attempts + 1,
                       locked_until = now() + make_interval(secs => :lease)
                WHERE id = :id AND (status IN ('received', 'failed')
                       OR (status = 'processing' AND locked_until < now()))
                RETURNING attempts
                """
            ),
            {"id": event_pk, "lease": float(config.get_payments_settings().payments_job_lease_seconds)},
        )
    ).first()
    await session.commit()
    if claimed is None:
        return
    attempts = int(claimed[0])
    event = (
        await session.execute(
            sa.select(WebhookEvent).where(WebhookEvent.id == event_pk).execution_options(populate_existing=True)
        )
    ).scalar_one()
    provider_event_id = event.event_id  # read now: a rollback below expires the loaded row
    try:
        outcome = await _handle(session, event, attempts)
    except (ProviderUnavailable, EventRetry) as exc:
        await session.rollback()
        await _mark(session, event_pk, FAILED, exc.code)
        raise EventRetry(exc.code) from None
    except ProviderRejected as exc:
        # The provider will not tell us about this object (deleted, other account): nothing to do.
        await session.rollback()
        await _mark(session, event_pk, IGNORED, exc.code)
        return
    except Exception:
        await session.rollback()
        await _mark(session, event_pk, FAILED, "internal_error")
        logger.exception("event_processing_failed", event_id=provider_event_id)
        raise
    await _mark(session, event_pk, outcome, None)


async def _mark(session: AsyncSession, event_pk: uuid.UUID, status: str, code: str | None) -> None:
    await session.execute(
        sa.update(WebhookEvent)
        .where(WebhookEvent.id == event_pk)
        .values(
            status=status,
            error_code=code[:64] if code else None,
            processed_at=datetime.now(UTC) if status in (PROCESSED, IGNORED) else None,
            locked_until=None,
        )
    )
    await session.commit()


async def _find_payment(session: AsyncSession, **refs: Any) -> Payment | None:
    conditions = []
    if refs.get("session_id"):
        conditions.append(Payment.provider_session_id == refs["session_id"])
    if refs.get("payment_intent"):
        conditions.append(Payment.provider_payment_intent_id == refs["payment_intent"])
    if refs.get("payment_id"):
        try:
            conditions.append(Payment.id == uuid.UUID(refs["payment_id"]))
        except ValueError:
            pass
    if not conditions:
        return None
    return (
        await session.execute(sa.select(Payment).where(sa.or_(*conditions)).limit(1))
    ).scalar_one_or_none()


def _unknown(attempts: int) -> str:
    """An event about a payment we cannot find. It may simply have arrived before our own commit
    of the checkout, so it is retried a few times before being set aside."""
    if attempts < _MAX_UNKNOWN_ATTEMPTS:
        raise EventRetry("payment_not_found")
    return IGNORED


async def _handle(session: AsyncSession, event: WebhookEvent, attempts: int) -> str:
    """Apply one event. The adapter has already classified it (`kind`) and named the provider
    objects it refers to (`refs`); everything below is the same for every provider."""
    provider = get_provider()
    kind = event.payload.get("kind", "ignore")
    hint = event.payload.get("hint")
    refs: dict[str, str] = event.payload.get("refs", {})

    if kind == "checkout":
        session_id = refs.get("session")
        if not session_id:
            return IGNORED
        payment = await _find_payment(session, session_id=session_id, payment_id=refs.get("payment_id"))
        if payment is None:
            return _unknown(attempts)
        checkout = await provider.retrieve_checkout(session_id)
        await service.sync_payment_from_checkout(session, payment.id, checkout, hint=hint)
        return PROCESSED

    if kind == "refund":
        refund_id = refs.get("refund")
        if not refund_id:
            return IGNORED
        reported = await provider.retrieve_refund(refund_id)
        payment = await _find_payment(session, payment_intent=reported.payment_intent_id)
        if payment is None:
            return _unknown(attempts)
        await service.apply_provider_refund(session, payment.id, reported)
        return PROCESSED

    if kind == "refunds_of_payment":
        intent = refs.get("payment_intent")
        payment = await _find_payment(session, payment_intent=intent)
        if payment is None:
            return _unknown(attempts) if intent else IGNORED
        for reported in await provider.list_refunds(intent or ""):
            await service.apply_provider_refund(session, payment.id, reported)
        return PROCESSED

    if kind == "dispute":
        dispute_id = refs.get("dispute")
        if not dispute_id:
            return IGNORED
        dispute = await provider.retrieve_dispute(dispute_id)
        payment = await _find_payment(session, payment_intent=dispute.payment_intent_id)
        if payment is None:
            return _unknown(attempts)
        await service.apply_dispute(session, payment.id, dispute)
        return PROCESSED

    return IGNORED  # event types this system does not use are stored and set aside


async def purge_old_events(session: AsyncSession, older_than_days: int) -> int:
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    result = await session.execute(
        sa.delete(WebhookEvent).where(
            WebhookEvent.status.in_((PROCESSED, IGNORED)), WebhookEvent.received_at < cutoff
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
