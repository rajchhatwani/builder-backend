"""Billing reconciliation: catch what webhooks missed (backend gaps A–C §4).

Stripe retries a webhook for about three days, then gives up; after that the
`subscriptions` row would stay stale forever. This job re-reads every Stripe-linked
subscription and applies it with the same rules as the webhook (`StripeWebhookService`),
and ends platform-granted trials that are past their date.

Run it on a schedule (hourly is plenty):

    python -m app.services.billing_reconcile

or on demand from the operator console (`POST /admin/billing/reconcile`).
Only rows that actually change get an audit entry (`billing.reconciled`).
"""

import asyncio
import logging
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import SubscriptionStatus
from app.models.platform import Subscription
from app.services import audit_service, stripe_client
from app.services.organization_service import OrganizationService

log = logging.getLogger(__name__)


@dataclass
class ReconcileReport:
    checked: int = 0  # Stripe-linked subscriptions fetched
    changed: int = 0  # rows whose plan/status/period moved
    failed: int = 0  # Stripe errors (retried on the next run)
    trials_expired: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _snapshot(sub: Subscription) -> tuple[object, ...]:
    return (sub.plan_id, sub.status, sub.current_period_end, sub.trial_ends_at)


async def reconcile(session: AsyncSession) -> ReconcileReport:
    from app.services.stripe_webhook_service import StripeWebhookService

    report = ReconcileReport()
    orgs = OrganizationService(session)

    # 1. Platform trials past their date.
    trials = list(
        (
            await session.execute(
                select(Subscription.organization_id).where(
                    Subscription.status == SubscriptionStatus.trial
                )
            )
        ).scalars()
    )
    for org_id in trials:
        sub = await session.get(Subscription, org_id, with_for_update=True, populate_existing=True)
        if sub is not None and await orgs.expire_trial_if_due(sub):
            report.trials_expired += 1
        await session.commit()

    # 2. Stripe-linked subscriptions, one at a time (each locks only its own row).
    key = get_settings().stripe_secret_key
    if key is None:
        return report
    linked = list(
        (
            await session.execute(
                select(Subscription.organization_id, Subscription.stripe_subscription_id).where(
                    Subscription.stripe_subscription_id.is_not(None)
                )
            )
        ).all()
    )
    webhook = StripeWebhookService(session)
    for org_id, stripe_sub_id in linked:
        report.checked += 1
        try:
            remote = await stripe_client.fetch_subscription(
                secret_key=key.get_secret_value(), subscription_id=str(stripe_sub_id)
            )
        except stripe_client.StripeError as exc:
            log.warning("reconcile: stripe fetch failed for org %s: %s", org_id, exc)
            report.failed += 1
            continue
        sub = await session.get(Subscription, org_id, with_for_update=True, populate_existing=True)
        if sub is None or sub.stripe_subscription_id != stripe_sub_id:
            await session.rollback()  # replaced while we were fetching; next run sees it
            continue
        before = _snapshot(sub)
        await webhook._apply_subscription(  # noqa: SLF001 — same rules as the webhook
            sub, remote, deleted=remote.get("status") == "canceled"
        )
        if _snapshot(sub) == before:
            await session.rollback()
            continue
        report.changed += 1
        await audit_service.record(
            session,
            action="billing.reconciled",
            via="system",
            organization_id=org_id,
            target_type="organization",
            target_id=org_id,
            detail={
                "from_plan": str(before[0]),
                "to_plan": sub.plan_id,
                "from_status": str(getattr(before[1], "value", before[1])),
                "to_status": sub.status.value,
            },
        )
        await session.commit()
    return report


async def _main() -> None:
    from app.db import get_session_factory

    async with get_session_factory()() as session:
        report = await reconcile(session)
    print(report.as_dict())  # noqa: T201 — a cron job's output


if __name__ == "__main__":
    asyncio.run(_main())
