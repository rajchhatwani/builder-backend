"""Outgoing webhooks, step 2 (generated): deliver one delivery (runs as the `webhook_delivery` job).

One attempt = load the delivery, sign with every live secret, POST through the SSRF-guarded egress, record the
outcome. Failures that can pass (network, timeout, DNS, 408/429/5xx) raise `RetryDelivery` so the jobs queue
retries with the job's own backoff; a refusal that will not pass (blocked address, redirect, other 4xx, no
secret) ends the delivery at once. After the last attempt the delivery is `failed`. Every failed attempt counts
toward the subscription's consecutive failures; reaching the limit disables the subscription (fail closed);
any success resets the count. The log keeps codes and numbers only: no body, header, URL or secret."""

import datetime as _dt
import json
import time
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models._base import utcnow
from app.webhooks import definitions, egress, secrets, signing, ssrf
from app.webhooks.models import (
    ACTIVE,
    CANCELLED,
    DELIVERED,
    DISABLED,
    FAILED,
    PENDING,
    Attempt,
    Delivery,
    Subscription,
)

logger = structlog.get_logger()

SessionFactory = async_sessionmaker[AsyncSession]


class RetryDelivery(Exception):
    """This attempt failed in a way that may pass: the job is retried with backoff."""


@dataclass(frozen=True)
class Outcome:
    state: str  # delivered | retry | failed | skipped
    code: str


def policy() -> ssrf.Policy:
    return ssrf.Policy(allow_http=definitions.ALLOW_HTTP, allowed_ports=tuple(definitions.ALLOWED_PORTS))


def body_for(delivery: Delivery) -> bytes:
    """The exact bytes that are signed and sent (canonical JSON, so a retry sends identical bytes)."""
    envelope = {
        "id": str(delivery.event_id),
        "type": delivery.event_type,
        "occurred_at": delivery.occurred_at.isoformat(),
        "data": delivery.payload,
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def classify(status: int) -> tuple[bool, str]:
    """(retryable, code) for an HTTP status that is not a success."""
    if 300 <= status < 400:
        return False, "redirect_not_followed"
    if status in (408, 425, 429) or status >= 500:
        return True, f"http_{status}"
    return False, f"http_{status}"


async def _live_secrets(session: AsyncSession, sub: Subscription, now: _dt.datetime) -> list[str]:
    found: list[str] = []
    for version in secrets.live_versions(sub, now):
        value = await secrets.get(session, sub.tenant_id, secrets.out_name(sub.id, version))
        if value is not None:
            found.append(value)
    return found


async def _finish(
    factory: SessionFactory,
    delivery_id: uuid.UUID,
    sub_id: uuid.UUID,
    attempt: int,
    code: str,
    status: int | None,
    millis: int,
    state: str,
    now: _dt.datetime,
) -> None:
    """Record the attempt and the delivery's new state, and update the subscription's failure count."""
    ok = state == DELIVERED
    async with factory() as session:
        session.add(Attempt(delivery_id=delivery_id, attempt=attempt, outcome=code, status_code=status, duration_ms=millis, created_at=now))
        values: dict[str, object] = {
            "attempts": attempt,
            "last_status_code": status,
            "last_error": None if ok else code,
        }
        if state in (DELIVERED, FAILED, CANCELLED):
            values.update(status=state, finished_at=now)
        await session.execute(sa.update(Delivery).where(Delivery.id == delivery_id).values(**values))
        if ok:
            await session.execute(
                sa.update(Subscription)
                .where(Subscription.id == sub_id, Subscription.consecutive_failures > 0)
                .values(consecutive_failures=0, updated_at=now)
            )
        else:
            over = Subscription.consecutive_failures + 1 >= definitions.MAX_CONSECUTIVE_FAILURES
            await session.execute(
                sa.update(Subscription)
                .where(Subscription.id == sub_id, Subscription.status == ACTIVE)
                .values(
                    consecutive_failures=Subscription.consecutive_failures + 1,
                    status=sa.case((over, DISABLED), else_=Subscription.status),
                    disabled_reason=sa.case((over, "consecutive_failures"), else_=Subscription.disabled_reason),
                    updated_at=now,
                )
            )
        await session.commit()


async def deliver(
    delivery_id: uuid.UUID, *, attempt: int, last_attempt: bool, factory: SessionFactory | None = None, now: _dt.datetime | None = None
) -> Outcome:
    if factory is None:
        from app.db import session_factory as factory
    stamp = now or utcnow()
    async with factory() as session:
        delivery = await session.get(Delivery, delivery_id)
        if delivery is None or delivery.status != PENDING:
            return Outcome("skipped", "not_pending")
        sub = await session.get(Subscription, delivery.subscription_id)
        if sub is None or sub.status != ACTIVE:
            delivery.status, delivery.finished_at, delivery.last_error = CANCELLED, stamp, "subscription_inactive"
            await session.commit()
            return Outcome("skipped", "subscription_inactive")
        signing_secrets = await _live_secrets(session, sub, stamp)
        url, sub_id, body = sub.url, sub.id, body_for(delivery)
    # the database connection is released here: nothing is held while the network is used
    if len(body) > definitions.MAX_PAYLOAD_BYTES:
        await _finish(factory, delivery_id, sub_id, attempt, "payload_too_large", None, 0, FAILED, stamp)
        return Outcome("failed", "payload_too_large")
    if not signing_secrets:
        await _finish(factory, delivery_id, sub_id, attempt, "no_secret", None, 0, FAILED, stamp)
        return Outcome("failed", "no_secret")
    unix = int(stamp.timestamp())
    headers = {
        signing.HEADER_ID: str(delivery_id),
        signing.HEADER_TIMESTAMP: str(unix),
        signing.HEADER_SIGNATURE: signing.signature_header(signing_secrets, str(delivery_id), unix, body),
    }
    started = time.monotonic()
    status: int | None = None
    retryable, code = False, "delivered"
    try:
        response = await egress.post(url, body, headers, policy=policy(), timeout=definitions.TIMEOUT_SECONDS)
        status = response.status
        if 200 <= status < 300:
            code = "delivered"
        else:
            retryable, code = classify(status)
    except ssrf.Blocked as exc:
        retryable, code = False, f"blocked_{exc.code}"
    except egress.EgressError as exc:
        retryable, code = exc.retryable, exc.code
    millis = round((time.monotonic() - started) * 1000)
    if code == "delivered":
        await _finish(factory, delivery_id, sub_id, attempt, code, status, millis, DELIVERED, stamp)
        return Outcome("delivered", code)
    if retryable and not last_attempt:
        await _finish(factory, delivery_id, sub_id, attempt, code, status, millis, PENDING, stamp)
        logger.warning("webhook_attempt_failed", delivery_id=str(delivery_id), attempt=attempt, outcome=code)
        return Outcome("retry", code)
    await _finish(factory, delivery_id, sub_id, attempt, code, status, millis, FAILED, stamp)
    logger.warning("webhook_delivery_failed", delivery_id=str(delivery_id), attempt=attempt, outcome=code)
    return Outcome("failed", code)


async def run_job(job_id: uuid.UUID, payload: dict[str, object], attempt: int, last_attempt: bool) -> None:
    """The body of the `webhook_delivery` job (see worker_job.py)."""
    try:
        delivery_id = uuid.UUID(str(payload["delivery_id"]))
    except (KeyError, ValueError):
        raise ValueError("bad webhook job payload") from None
    outcome = await deliver(delivery_id, attempt=attempt, last_attempt=last_attempt)
    if outcome.state == "retry":
        raise RetryDelivery(outcome.code)
