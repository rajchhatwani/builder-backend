"""Org billing: Checkout (Phase B), Billing Portal and seat sync (Phase C).

One Stripe Customer and one Stripe Subscription per org (§10). An org without a live
Stripe subscription buys through Checkout; an org that has one changes plan, card or
cancels through the Billing Portal, so a second subscription is never created.

The plan does not change here. Per PLATFORM_SAAS_PLAN §6.3 the platform's view of the
plan only moves on a Stripe event (Phase C webhook) or by an operator via
`/admin/organizations/{id}/plan`. Stripe is authoritative on money, the platform on usage.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.exceptions import AppError
from app.models.enums import AuditResult, SubscriptionStatus
from app.models.platform import Organization, Plan, PlatformUser, Subscription
from app.services import audit_service, stripe_client
from app.services.organization_service import OrganizationService

log = logging.getLogger(__name__)


# A Stripe subscription in these states is live: buying again would create a second one.
LIVE_STATUSES = frozenset(
    {SubscriptionStatus.active, SubscriptionStatus.trial, SubscriptionStatus.past_due}
)


def checkout_available() -> bool:
    return get_settings().stripe_secret_key is not None


def has_live_stripe_subscription(sub: Subscription) -> bool:
    return sub.stripe_subscription_id is not None and sub.status in LIVE_STATUSES


def portal_available(sub: Subscription) -> bool:
    return checkout_available() and sub.stripe_customer_id is not None


def _unavailable() -> AppError:
    return AppError(
        code="billing_unavailable",
        message="online billing is not configured on this platform",
        status_code=503,
    )


def _plan_page(org: Organization) -> str:
    return f"{get_settings().public_app_url.rstrip('/')}/#/org/{org.slug}/plan"


def _price_for(plan: Plan) -> str | None:
    """The Stripe Price for a plan that can be bought online, else None. free has no
    price; enterprise is sales-led (not public); unmapped plans are not sold online."""
    if not plan.is_public or not plan.monthly_price_usd:
        return None
    return get_settings().stripe_price_ids.get(plan.id)


class BillingService:
    def __init__(self, session: AsyncSession) -> None:
        self.db = session

    async def upgrade_options(self, current_plan_id: str) -> list[Plan]:
        """Plans the org could switch to via Checkout, cheapest first."""
        if not checkout_available():
            return []
        plans = (
            await self.db.execute(select(Plan).order_by(Plan.monthly_price_usd, Plan.id))
        ).scalars()
        return [p for p in plans if p.id != current_plan_id and _price_for(p) is not None]

    async def start_checkout(
        self, org: Organization, *, plan_id: str, actor: PlatformUser
    ) -> stripe_client.CheckoutSession:
        orgs = OrganizationService(self.db)
        current, sub = await orgs.plan_and_subscription(org.id)
        target = await self.db.get(Plan, plan_id)
        if target is None:
            raise AppError(code="not_found", message="plan not found", status_code=404)
        if target.id == current.id:
            raise AppError(
                code="conflict", message="the organization is already on this plan", status_code=409
            )

        if has_live_stripe_subscription(sub):
            raise AppError(
                code="already_subscribed",
                message=(
                    "the organization already has a subscription; change the plan from "
                    "Manage billing"
                ),
                status_code=409,
            )
        settings = get_settings()
        if settings.stripe_secret_key is None:
            raise _unavailable()
        price_id = _price_for(target)
        if price_id is None:
            raise AppError(
                code="plan_not_purchasable",
                message=f"plan '{target.id}' cannot be purchased online",
                status_code=422,
            )

        seats = (await orgs.usage(org.id))["seats_used"] or 1
        plan_page = _plan_page(org)
        actor_id, actor_email = actor.id, actor.email
        try:
            session = await stripe_client.create_checkout_session(
                secret_key=settings.stripe_secret_key.get_secret_value(),
                price_id=price_id,
                quantity=seats,
                organization_id=org.id,
                plan_id=target.id,
                customer_id=sub.stripe_customer_id,
                customer_email=None if sub.stripe_customer_id else actor_email,
                success_url=f"{plan_page}?checkout=success",
                cancel_url=f"{plan_page}?checkout=cancel",
            )
        except stripe_client.StripeError as exc:
            log.warning("stripe checkout failed for org %s: %s", org.id, exc)
            raise AppError(
                code="billing_provider_error",
                message="the payment provider could not start checkout; try again later",
                status_code=502,
            ) from exc

        # Only Stripe ids in the audit trail, never card or customer data (§10).
        await audit_service.record(
            self.db,
            action="plan.checkout_started",
            actor_id=actor_id,
            actor_email=actor_email,
            organization_id=org.id,
            target_type="organization",
            target_id=org.id,
            detail={"plan_id": target.id, "checkout_session_id": session.id},
        )
        await self.db.commit()
        return session

    async def start_portal(self, org: Organization, *, actor: PlatformUser) -> str:
        """A Billing Portal session for the org's Stripe Customer. Whatever the admin changes
        there comes back as a `customer.subscription.*` webhook — never applied from here."""
        settings = get_settings()
        if settings.stripe_secret_key is None:
            raise _unavailable()
        _plan, sub = await OrganizationService(self.db).plan_and_subscription(org.id)
        if sub.stripe_customer_id is None:
            raise AppError(
                code="no_billing_account",
                message="the organization has no billing account yet; upgrade first",
                status_code=409,
            )
        customer_id, actor_id, actor_email = sub.stripe_customer_id, actor.id, actor.email
        try:
            url = await stripe_client.create_portal_session(
                secret_key=settings.stripe_secret_key.get_secret_value(),
                customer_id=customer_id,
                return_url=_plan_page(org),
            )
        except stripe_client.StripeError as exc:
            log.warning("stripe portal failed for org %s: %s", org.id, exc)
            raise AppError(
                code="billing_provider_error",
                message="the payment provider is not reachable; try again later",
                status_code=502,
            ) from exc
        await audit_service.record(
            self.db,
            action="billing.portal_opened",
            actor_id=actor_id,
            actor_email=actor_email,
            organization_id=org.id,
            target_type="organization",
            target_id=org.id,
        )
        await self.db.commit()
        return url

    async def sync_seats(self, organization_id: uuid.UUID, *, new_period: bool = False) -> None:
        """C.4: make the Stripe seat quantity follow the member count (§10), high-water-mark
        (§6.4): mid-cycle it only goes up, with proration; at a new period it resets to the
        current members, without proration.

        Best effort, after the membership change has committed: a Stripe failure is logged
        and audited, never raised — the next change (or renewal) catches up. Billed seats
        are members only; pending invites are not billed.
        """
        settings = get_settings()
        if settings.stripe_secret_key is None:
            return
        sub = await self.db.get(Subscription, organization_id, populate_existing=True)
        if sub is None or not has_live_stripe_subscription(sub):
            return
        sub_id = sub.stripe_subscription_id
        assert sub_id is not None
        members = await OrganizationService(self.db).count_members(organization_id)
        key = settings.stripe_secret_key.get_secret_value()
        try:
            info = await stripe_client.get_subscription(secret_key=key, subscription_id=sub_id)
            target = max(members, 1) if new_period else max(members, info.quantity)
            if target == info.quantity:
                return
            await stripe_client.set_item_quantity(
                secret_key=key,
                item_id=info.item_id,
                quantity=target,
                proration_behavior="none" if new_period else "create_prorations",
            )
        except stripe_client.StripeError as exc:
            log.warning("stripe seat sync failed for org %s: %s", organization_id, exc)
            await audit_service.record(
                self.db,
                action="billing.seat_sync_failed",
                result=AuditResult.error,
                via="stripe",
                organization_id=organization_id,
                target_type="organization",
                target_id=organization_id,
                detail={"stripe_subscription_id": sub_id, "members": members},
            )
            await self.db.commit()
            return
        await audit_service.record(
            self.db,
            action="billing.seats_synced",
            via="stripe",
            organization_id=organization_id,
            target_type="organization",
            target_id=organization_id,
            detail={"stripe_subscription_id": sub_id, "from": info.quantity, "to": target},
        )
        await self.db.commit()
