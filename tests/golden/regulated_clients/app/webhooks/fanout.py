"""Outgoing webhooks, step 1 (generated): turn a published event into one delivery per matching subscription.

Registered on the events bus for every event type the spec lists (default deny: other events are never
announced). Runs inside the relay, once per event (at least once: a repeat is harmless, because
(subscription, event) is unique and the job is keyed by the delivery id). The delivery row and its job are
written in ONE transaction, so there is never a delivery without a job or a job without a delivery."""

import uuid

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import session_factory
from app.events.bus import Event, subscribe
from app.jobs import queue
from app.models._base import utcnow
from app.webhooks import definitions
from app.webhooks.models import ACTIVE, Delivery, Subscription

logger = structlog.get_logger()


async def fan_out(event: Event) -> None:
    if event.type not in definitions.EVENTS:
        return
    if definitions.MULTI_TENANT and event.tenant_id is None:
        return  # a tenant-less event reaches no tenant's subscription
    async with session_factory() as session:
        scope = Subscription.tenant_id == event.tenant_id if definitions.MULTI_TENANT else Subscription.tenant_id.is_(None)
        subs = (await session.execute(sa.select(Subscription).where(scope, Subscription.status == ACTIVE))).scalars()
        made = 0
        for sub in list(subs):
            if event.type not in sub.event_types:
                continue
            delivery_id = (
                await session.execute(
                    pg_insert(Delivery)
                    .values(
                        id=uuid.uuid4(),
                        subscription_id=sub.id,
                        tenant_id=event.tenant_id if definitions.MULTI_TENANT else None,
                        event_id=event.id,
                        event_type=event.type,
                        occurred_at=event.occurred_at,
                        payload=event.payload,
                        status="pending",
                        attempts=0,
                        created_at=utcnow(),
                    )
                    .on_conflict_do_nothing(constraint="uq_wh_deliveries_subscription_event")
                    .returning(Delivery.id)
                )
            ).scalar_one_or_none()
            if delivery_id is None:
                continue  # this event was already turned into a delivery for this subscription
            await queue.enqueue(
                definitions.JOB,
                {"delivery_id": str(delivery_id)},
                session=session,
                dedupe_key=f"wh:{delivery_id}",
                tenant_id=event.tenant_id if definitions.MULTI_TENANT else None,
            )
            made += 1
        await session.commit()
    if made:
        logger.info("webhook_deliveries_created", event_id=str(event.id), event_type=event.type, count=made)


for _event_type in definitions.EVENTS:
    subscribe(_event_type)(fan_out)
