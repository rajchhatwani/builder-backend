"""Phase C.3 — apply verified Stripe events to the org's `subscriptions` row (§6.3, §10).

The caller (the webhook route) has already checked the signature. This service:
  1. maps the event to an org — metadata / `client_reference_id` that our own Checkout set,
     else the stored `stripe_subscription_id`, else the stored `stripe_customer_id`;
  2. locks the subscription row (`FOR UPDATE`) so deliveries for one org serialize;
  3. drops redeliveries (the Stripe event id is the audit row's target) and events older
     than the newest one already applied (Stripe does not guarantee order);
  4. updates plan / status / period / Stripe ids, and audits the event id only.

Stripe is authoritative on money, the platform on usage (§6.1): an event can move the plan,
but never deletes members or projects. A downgrade below current usage is allowed and
audited as `plan.over_cap`; the §6.2 checks then refuse new growth until usage fits (§6.3).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import AuditResult, SubscriptionStatus
from app.models.platform import AuditLog, Plan, Subscription
from app.services import audit_service
from app.services.billing_service import LIVE_STATUSES
from app.services.organization_service import OrganizationService

log = logging.getLogger(__name__)

AUDIT_ACTION = "billing.stripe_event"
HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_failed",
    }
)
# Where an org lands when its Stripe subscription ends. A literal, not
# organization_service.DEFAULT_PERSONAL_PLAN_ID: that one is about sign-up.
CANCELED_PLAN_ID = "free"

# Stripe subscription status → ours. Missing (`incomplete`) = leave the status alone: the
# first payment is still being attempted and `checkout.session.completed` decides.
_STATUS = {
    "active": SubscriptionStatus.active,
    "trialing": SubscriptionStatus.trial,
    "past_due": SubscriptionStatus.past_due,
    "unpaid": SubscriptionStatus.past_due,
    "paused": SubscriptionStatus.past_due,
    "canceled": SubscriptionStatus.canceled,
    "incomplete_expired": SubscriptionStatus.canceled,
}
_PAID_CHECKOUT = frozenset({"paid", "no_payment_required"})


@dataclass(frozen=True)
class WebhookResult:
    """`outcome`: applied | duplicate | stale | ignored | unknown_org | customer_mismatch.
    `period_renewed` tells the caller to restart the high-water seat count (§6.4)."""

    outcome: str
    organization_id: uuid.UUID | None = None
    period_renewed: bool = False


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _ts(value: object) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if isinstance(value, int | float) else None


def _invoice_subscription(invoice: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """(subscription id, subscription metadata) across API versions: older ones put
    `subscription` on the invoice, 2025+ ones under `parent.subscription_details`."""
    parent = (invoice.get("parent") or {}).get("subscription_details") or {}
    legacy = invoice.get("subscription_details") or {}
    sub_id = invoice.get("subscription") or parent.get("subscription")
    if isinstance(sub_id, dict):  # expanded object
        sub_id = sub_id.get("id")
    metadata = parent.get("metadata") or legacy.get("metadata") or {}
    return (str(sub_id) if sub_id else None), metadata


def _first_item(subscription: dict[str, Any]) -> dict[str, Any]:
    items = (subscription.get("items") or {}).get("data") or []
    return items[0] if items else {}


def _expected_livemode() -> bool | None:
    """True for an sk_live_/rk_live_ key, False for test keys, None when no key is set."""
    key = get_settings().stripe_secret_key
    if key is None:
        return None
    return key.get_secret_value().startswith(("sk_live_", "rk_live_"))


class StripeWebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.db = session

    async def handle(self, event: dict[str, Any]) -> WebhookResult:
        event_type = str(event.get("type", ""))
        if event_type not in HANDLED_EVENTS:
            return WebhookResult("ignored")
        data = event.get("data")
        obj = data.get("object") if isinstance(data, dict) else None
        if not isinstance(obj, dict) or not isinstance(event.get("id"), str):
            # Signed but not shaped like a Stripe event: acknowledge it (a 5xx makes Stripe retry
            # for days) and do nothing.
            log.warning("stripe event %s (%s) is malformed; ignored", event.get("id"), event_type)
            return WebhookResult("ignored")
        org_id = await self._resolve_org(event_type, obj)
        sub = await self._lock(org_id) if org_id is not None else None
        if org_id is None or sub is None:
            log.warning("stripe event %s (%s) maps to no organization", event["id"], event_type)
            return WebhookResult("unknown_org")

        if await self._seen(event["id"]):
            await self.db.rollback()
            return WebhookResult("duplicate", org_id)

        expected_live = _expected_livemode()
        if expected_live is not None and bool(event.get("livemode")) != expected_live:
            # A test-mode platform must never act on live events, or the other way round
            # (e.g. one webhook endpoint registered in both modes).
            await self._record(
                event,
                org_id,
                int(event.get("created") or 0),
                "livemode_mismatch",
                AuditResult.denied,
            )
            return WebhookResult("livemode_mismatch", org_id)

        created = int(event.get("created") or 0)
        customer = obj.get("customer")
        customer = customer.get("id") if isinstance(customer, dict) else customer
        if customer and sub.stripe_customer_id and customer != sub.stripe_customer_id:
            # One Stripe Customer per org (§10). Never let another customer's event move it.
            await self._record(event, org_id, created, "customer_mismatch", AuditResult.denied)
            return WebhookResult("customer_mismatch", org_id)
        if self._is_other_subscription(event_type, obj, sub):
            # A late event from a subscription the org has since replaced (canceled, then
            # bought again). One Stripe Subscription per org (§10): only the live one counts.
            await self._record(event, org_id, created, "other_subscription")
            return WebhookResult("other_subscription", org_id)
        if created < await self._newest_applied(org_id):
            await self._record(event, org_id, created, "stale")
            return WebhookResult("stale", org_id)

        old_plan = sub.plan_id
        renewed = False
        if event_type == "checkout.session.completed":
            self._apply_checkout(sub, obj)
        elif event_type == "invoice.payment_failed":
            if sub.status in (SubscriptionStatus.active, SubscriptionStatus.trial):
                sub.status = SubscriptionStatus.past_due
        else:
            renewed = await self._apply_subscription(
                sub, obj, deleted=event_type.endswith("deleted")
            )

        if customer and sub.stripe_customer_id is None:
            sub.stripe_customer_id = str(customer)
        await self.db.flush()
        if sub.plan_id != old_plan:
            await self._audit_over_cap(org_id, sub)
        await self._record(
            event,
            org_id,
            created,
            "applied",
            extra={"plan_id": sub.plan_id, "status": sub.status.value},
        )
        return WebhookResult("applied", org_id, period_renewed=renewed)

    # -- event kinds ------------------------------------------------------------------

    @staticmethod
    def _is_other_subscription(event_type: str, obj: dict[str, Any], sub: Subscription) -> bool:
        if event_type == "checkout.session.completed":
            return False  # a purchase is how a replacement subscription arrives
        if event_type == "invoice.payment_failed":
            event_sub, _ = _invoice_subscription(obj)
        else:
            event_sub = obj.get("id")
        live = sub.stripe_subscription_id is not None and sub.status in LIVE_STATUSES
        return bool(live and event_sub and event_sub != sub.stripe_subscription_id)

    def _apply_checkout(self, sub: Subscription, session: dict[str, Any]) -> None:
        if session.get("subscription"):
            sub.stripe_subscription_id = str(session["subscription"])
        if session.get("payment_status") not in _PAID_CHECKOUT:
            return  # e.g. a bank debit still clearing; the subscription event will follow
        plan_id = (session.get("metadata") or {}).get("plan_id")
        if plan_id and self._plan_known(plan_id):
            sub.plan_id = plan_id
        sub.status = SubscriptionStatus.active

    async def _apply_subscription(
        self, sub: Subscription, stripe_sub: dict[str, Any], *, deleted: bool
    ) -> bool:
        """Returns True when a new billing period started (seat high-water mark resets)."""
        sub.stripe_subscription_id = str(stripe_sub.get("id") or sub.stripe_subscription_id)
        status = (
            SubscriptionStatus.canceled if deleted else _STATUS.get(str(stripe_sub.get("status")))
        )
        if status is SubscriptionStatus.canceled:
            sub.status = status
            sub.plan_id = CANCELED_PLAN_ID
            sub.current_period_end = None
            return False
        if status is not None:
            sub.status = status

        item = _first_item(stripe_sub)
        plan_id = self._plan_for_price((item.get("price") or {}).get("id"))
        if plan_id is None:
            candidate = (stripe_sub.get("metadata") or {}).get("plan_id")
            plan_id = candidate if candidate and self._plan_known(candidate) else None
        # Only a subscription Stripe considers live unlocks a plan; `incomplete` (first
        # payment pending) leaves the plan where it is.
        if plan_id is not None and status in LIVE_STATUSES:
            sub.plan_id = plan_id
        sub.trial_ends_at = _ts(stripe_sub.get("trial_end"))

        period_end = _ts(item.get("current_period_end") or stripe_sub.get("current_period_end"))
        renewed = (
            period_end is not None
            and sub.current_period_end is not None
            and period_end > sub.current_period_end
        )
        if period_end is not None:
            sub.current_period_end = period_end
        return renewed

    # -- mapping ----------------------------------------------------------------------

    async def _resolve_org(self, event_type: str, obj: dict[str, Any]) -> uuid.UUID | None:
        metadata = obj.get("metadata") or {}
        sub_id: str | None = None
        if event_type == "checkout.session.completed":
            if obj.get("mode") != "subscription":
                return None
            org_id = _uuid(obj.get("client_reference_id")) or _uuid(metadata.get("organization_id"))
            if org_id is not None:
                return org_id
        elif event_type == "invoice.payment_failed":
            sub_id, sub_metadata = _invoice_subscription(obj)
            metadata = sub_metadata
        else:
            sub_id = obj.get("id")
        if sub_id:
            found = await self._org_by(Subscription.stripe_subscription_id == sub_id)
            if found is not None:
                return found
        org_id = _uuid(metadata.get("organization_id"))
        if org_id is not None:
            return org_id
        customer = obj.get("customer")
        if isinstance(customer, str) and customer:
            return await self._org_by(Subscription.stripe_customer_id == customer)
        return None

    async def _org_by(self, condition: Any) -> uuid.UUID | None:
        rows = (
            (await self.db.execute(select(Subscription.organization_id).where(condition).limit(2)))
            .scalars()
            .all()
        )
        return rows[0] if len(rows) == 1 else None

    def _plan_for_price(self, price_id: object) -> str | None:
        if not price_id:
            return None
        by_price = {v: k for k, v in get_settings().stripe_price_ids.items()}
        return by_price.get(str(price_id))

    def _plan_known(self, plan_id: str) -> bool:
        return plan_id in get_settings().stripe_price_ids or plan_id == CANCELED_PLAN_ID

    # -- persistence ------------------------------------------------------------------

    async def _lock(self, org_id: uuid.UUID) -> Subscription | None:
        return (
            await self.db.execute(
                select(Subscription)
                .where(Subscription.organization_id == org_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def _seen(self, event_id: str) -> bool:
        found = await self.db.execute(
            select(AuditLog.id)
            .where(
                AuditLog.action == AUDIT_ACTION,
                AuditLog.target_type == "stripe_event",
                AuditLog.target_id == event_id,
            )
            .limit(1)
        )
        return found.first() is not None

    async def _newest_applied(self, org_id: uuid.UUID) -> int:
        newest = (
            await self.db.execute(
                select(func.max(AuditLog.detail["event_created"].as_integer())).where(
                    AuditLog.action == AUDIT_ACTION,
                    AuditLog.organization_id == org_id,
                    AuditLog.detail["outcome"].as_string() == "applied",
                )
            )
        ).scalar_one_or_none()
        return int(newest or 0)

    async def _record(
        self,
        event: dict[str, Any],
        org_id: uuid.UUID,
        created: int,
        outcome: str,
        result: AuditResult = AuditResult.ok,
        extra: dict[str, object] | None = None,
    ) -> None:
        """Only Stripe ids and our own plan/status — no card, no customer data (§10)."""
        await audit_service.record(
            self.db,
            action=AUDIT_ACTION,
            result=result,
            via="stripe",
            organization_id=org_id,
            target_type="stripe_event",
            target_id=str(event["id"]),
            detail={
                "event_type": str(event.get("type")),
                "event_created": created,
                "outcome": outcome,
                **(extra or {}),
            },
        )
        await self.db.commit()

    async def _audit_over_cap(self, org_id: uuid.UUID, sub: Subscription) -> None:
        plan = await self.db.get(Plan, sub.plan_id)
        if plan is None:
            return
        usage = await OrganizationService(self.db).usage(org_id)
        seats_used = int(usage["seats_used"] or 0) + int(usage["pending_invites"] or 0)
        seats_cap, projects_cap = usage["seats_cap"], usage["projects_cap"]
        projects_used = int(usage["projects_used"] or 0)
        over_seats = seats_cap is not None and seats_used > seats_cap
        over_projects = projects_cap is not None and projects_used > projects_cap
        if not (over_seats or over_projects):
            return
        await audit_service.record(
            self.db,
            action="plan.over_cap",
            via="stripe",
            organization_id=org_id,
            target_type="organization",
            target_id=org_id,
            detail={
                "plan_id": plan.id,
                "seats_used": seats_used,
                "seats_cap": seats_cap,
                "projects_used": projects_used,
                "projects_cap": projects_cap,
            },
        )
