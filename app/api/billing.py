"""Phase C.3 — the Stripe webhook endpoint.

The one unauthenticated billing route. It trusts nothing until the `Stripe-Signature`
HMAC over the raw body verifies; a failed check is a generic 400 (the reason goes to the
log, never to the caller). A verified event is answered 200 whether it was applied or
deliberately skipped, so Stripe stops retrying; only an unexpected failure is a 5xx, which
Stripe retries with backoff — and redeliveries are idempotent.
"""

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.exceptions import AppError
from app.services import stripe_client
from app.services.billing_service import BillingService
from app.services.stripe_webhook_service import StripeWebhookService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])

# Stripe events are a few KB; refuse anything far larger before hashing it.
MAX_WEBHOOK_BYTES = 256 * 1024


@router.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request, db: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    settings = get_settings()
    secrets = settings.stripe_webhook_secrets()
    if not secrets:
        raise AppError(
            code="billing_unavailable",
            message="the billing webhook is not configured",
            status_code=503,
        )
    payload = await request.body()
    try:
        if len(payload) > MAX_WEBHOOK_BYTES:
            raise stripe_client.WebhookSignatureError("body_too_large")
        event = stripe_client.verify_webhook(
            payload,
            request.headers.get("stripe-signature"),
            secrets,
            tolerance=settings.stripe_webhook_tolerance_seconds,
        )
    except stripe_client.WebhookSignatureError as exc:
        log.warning("stripe webhook rejected: %s", exc.reason)
        raise AppError(
            code="invalid_webhook", message="the webhook could not be accepted", status_code=400
        ) from None

    result = await StripeWebhookService(db).handle(event)
    if result.period_renewed and result.organization_id is not None:
        # The new period's bill starts from today's members (§6.4). Best effort.
        await BillingService(db).sync_seats(result.organization_id, new_period=True)
    return {"received": "true", "outcome": result.outcome}
