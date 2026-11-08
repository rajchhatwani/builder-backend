"""Phase C step 3 — the Stripe webhook (PLATFORM_SAAS_PLAN §6.3, §10, §12.C.3).

`POST /billing/stripe/webhook` is the one unauthenticated billing entry. It trusts nothing
until the `Stripe-Signature` HMAC checks out, then syncs the org's `subscriptions` row on
`checkout.session.completed`, `customer.subscription.*` and `invoice.payment_failed`.
Every applied event leaves a `billing.stripe_event` audit row whose target is the Stripe
event id (and nothing else from Stripe: no card, no customer email — §10). Stripe retries
and reorders deliveries, so a redelivered event is a no-op and an older event never
overwrites a newer one.
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.enums import SubscriptionStatus
from app.models.platform import AuditLog, Subscription
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]
WEBHOOK = "/billing/stripe/webhook"
SECRET = "whsec_test_secret"


@pytest.fixture
def webhook_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUILDER_STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("BUILDER_STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv(
        "BUILDER_STRIPE_PRICE_IDS", '{"team": "price_team", "business": "price_business"}'
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def sign(payload: bytes, secret: str = SECRET, timestamp: int | None = None) -> str:
    t = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={digest}"


def event(
    type_: str, obj: dict[str, Any], *, created: int | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "object": "event",
        "type": type_,
        "created": created if created is not None else int(time.time()),
        "livemode": False,
        "data": {"object": obj, **extra},
    }


async def deliver(client: AsyncClient, evt: dict[str, Any], **sign_kw: Any):  # noqa: ANN201
    payload = json.dumps(evt).encode()
    return await client.post(
        WEBHOOK,
        content=payload,
        headers={"Stripe-Signature": sign(payload, **sign_kw), "Content-Type": "application/json"},
    )


def checkout_completed(org_id: uuid.UUID, plan_id: str = "business", **over: Any) -> dict:
    obj = {
        "id": "cs_test_1",
        "object": "checkout.session",
        "mode": "subscription",
        "client_reference_id": str(org_id),
        "customer": "cus_123",
        "subscription": "sub_123",
        "payment_status": "paid",
        "status": "complete",
        "customer_details": {"email": "payer@example.com"},
        "metadata": {"organization_id": str(org_id), "plan_id": plan_id},
    }
    obj.update(over)
    return obj


def subscription_obj(
    org_id: uuid.UUID | None,
    *,
    status: str = "active",
    price: str = "price_business",
    period_end: int = 1_900_000_000,
    sub_id: str = "sub_123",
    customer: str = "cus_123",
    quantity: int = 1,
) -> dict[str, Any]:
    return {
        "id": sub_id,
        "object": "subscription",
        "customer": customer,
        "status": status,
        "trial_end": None,
        "current_period_end": period_end,
        "metadata": {"organization_id": str(org_id)} if org_id else {},
        "items": {
            "data": [
                {
                    "id": "si_1",
                    "quantity": quantity,
                    "price": {"id": price},
                    "current_period_end": period_end,
                }
            ]
        },
    }


async def _team_org(client: AsyncClient) -> uuid.UUID:
    r = await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


async def _sub(factory: Factory, org_id: uuid.UUID) -> Subscription:
    async with factory() as session:
        sub = await session.get(Subscription, org_id)
        assert sub is not None
        return sub


async def _set_sub(factory: Factory, org_id: uuid.UUID, **fields: Any) -> None:
    async with factory() as session:
        sub = await session.get(Subscription, org_id)
        assert sub is not None
        for key, value in fields.items():
            setattr(sub, key, value)
        await session.commit()


async def _audit(factory: Factory, action: str) -> list[AuditLog]:
    async with factory() as session:
        rows = await session.execute(select(AuditLog).where(AuditLog.action == action))
        return list(rows.scalars())


# -- signature ---------------------------------------------------------------------------


async def test_unsigned_or_badly_signed_events_are_rejected(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    org_id = await _team_org(client)
    evt = event("checkout.session.completed", checkout_completed(org_id))
    payload = json.dumps(evt).encode()

    missing = await anon_client.post(WEBHOOK, content=payload)
    wrong_secret = await deliver(anon_client, evt, secret="whsec_attacker")
    too_old = await deliver(anon_client, evt, timestamp=int(time.time()) - 3600)
    tampered = await anon_client.post(
        WEBHOOK,
        content=payload.replace(b"business", b"enterprise"),
        headers={"Stripe-Signature": sign(payload)},
    )
    for r in (missing, wrong_secret, too_old, tampered):
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "invalid_webhook"
        assert SECRET not in r.text

    sub = await _sub(session_factory, org_id)
    assert sub.plan_id == "team" and sub.stripe_customer_id is None
    assert await _audit(session_factory, "billing.stripe_event") == []


async def test_webhook_is_unavailable_until_a_secret_is_configured(
    anon_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BUILDER_STRIPE_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    r = await anon_client.post(WEBHOOK, content=b"{}", headers={"Stripe-Signature": "t=1,v1=00"})
    assert r.status_code == 503
    assert r.json()["code"] == "billing_unavailable"
    get_settings.cache_clear()


async def test_rotated_secrets_are_both_accepted(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    webhook_configured: None,
) -> None:
    """During a secret roll Stripe signs with the new secret; both must verify."""
    monkeypatch.setenv("BUILDER_STRIPE_WEBHOOK_SECRET", f"whsec_old,{SECRET}")
    get_settings.cache_clear()
    org_id = await _team_org(client)
    r = await deliver(anon_client, event("checkout.session.completed", checkout_completed(org_id)))
    assert r.status_code == 200, r.text


# -- checkout.session.completed -----------------------------------------------------------


async def test_checkout_completed_moves_the_plan_and_stamps_stripe_ids(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    org_id = await _team_org(client)
    evt = event("checkout.session.completed", checkout_completed(org_id))
    r = await deliver(anon_client, evt)
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "applied"

    sub = await _sub(session_factory, org_id)
    assert sub.plan_id == "business"
    assert sub.status is SubscriptionStatus.active
    assert sub.stripe_customer_id == "cus_123"
    assert sub.stripe_subscription_id == "sub_123"

    (row,) = await _audit(session_factory, "billing.stripe_event")
    assert row.organization_id == org_id
    assert row.target_type == "stripe_event" and row.target_id == evt["id"]
    assert row.actor_id is None
    assert row.detail["event_type"] == "checkout.session.completed"
    assert row.detail["plan_id"] == "business"
    # Only Stripe ids, never the payer's personal data (§10).
    assert "payer@example.com" not in json.dumps(row.detail)


async def test_checkout_awaiting_payment_stamps_ids_but_keeps_the_plan(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    org_id = await _team_org(client)
    obj = checkout_completed(org_id, payment_status="unpaid")
    r = await deliver(anon_client, event("checkout.session.completed", obj))
    assert r.status_code == 200
    sub = await _sub(session_factory, org_id)
    assert sub.plan_id == "team"
    assert sub.stripe_customer_id == "cus_123"
    assert sub.stripe_subscription_id == "sub_123"


async def test_redelivered_event_is_applied_once(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    org_id = await _team_org(client)
    evt = event("checkout.session.completed", checkout_completed(org_id))
    assert (await deliver(anon_client, evt)).json()["outcome"] == "applied"
    again = await deliver(anon_client, evt)
    assert again.status_code == 200
    assert again.json()["outcome"] == "duplicate"
    assert len(await _audit(session_factory, "billing.stripe_event")) == 1


async def test_event_for_an_unknown_org_is_acknowledged_and_ignored(
    anon_client: AsyncClient, session_factory: Factory, webhook_configured: None
) -> None:
    """A 2xx stops Stripe retrying an event we will never be able to map."""
    r = await deliver(
        anon_client, event("checkout.session.completed", checkout_completed(uuid.uuid4()))
    )
    assert r.status_code == 200
    assert r.json()["outcome"] == "unknown_org"


async def test_event_for_another_customer_is_refused(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    """The org already pays through cus_real; an event naming another customer is not applied."""
    org_id = await _team_org(client)
    await _set_sub(session_factory, org_id, stripe_customer_id="cus_real")
    r = await deliver(
        anon_client,
        event("checkout.session.completed", checkout_completed(org_id, customer="cus_other")),
    )
    assert r.status_code == 200
    assert r.json()["outcome"] == "customer_mismatch"
    sub = await _sub(session_factory, org_id)
    assert sub.plan_id == "team" and sub.stripe_customer_id == "cus_real"


async def test_unhandled_event_types_are_acknowledged(
    anon_client: AsyncClient, session_factory: Factory, webhook_configured: None
) -> None:
    r = await deliver(anon_client, event("charge.succeeded", {"id": "ch_1", "object": "charge"}))
    assert r.status_code == 200
    assert r.json()["outcome"] == "ignored"
    assert await _audit(session_factory, "billing.stripe_event") == []


# -- customer.subscription.* --------------------------------------------------------------


async def test_subscription_updated_syncs_plan_status_and_period(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    org_id = await _team_org(client)
    obj = subscription_obj(org_id, status="trialing", price="price_team", period_end=1_900_000_000)
    r = await deliver(anon_client, event("customer.subscription.updated", obj))
    assert r.status_code == 200, r.text
    sub = await _sub(session_factory, org_id)
    assert sub.plan_id == "team"
    assert sub.status is SubscriptionStatus.trial
    assert sub.current_period_end == datetime.fromtimestamp(1_900_000_000, UTC)
    assert sub.stripe_subscription_id == "sub_123"

    r = await deliver(anon_client, event("customer.subscription.updated", subscription_obj(org_id)))
    sub = await _sub(session_factory, org_id)
    assert sub.plan_id == "business" and sub.status is SubscriptionStatus.active


async def test_subscription_found_by_stripe_id_without_metadata(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    org_id = await _team_org(client)
    await _set_sub(
        session_factory, org_id, stripe_customer_id="cus_123", stripe_subscription_id="sub_123"
    )
    r = await deliver(
        anon_client,
        event("customer.subscription.updated", subscription_obj(None, status="past_due")),
    )
    assert r.json()["outcome"] == "applied"
    assert (await _sub(session_factory, org_id)).status is SubscriptionStatus.past_due


async def test_subscription_deleted_downgrades_to_free(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    org_id = await _team_org(client)
    await _set_sub(
        session_factory,
        org_id,
        plan_id="business",
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
    )
    obj = subscription_obj(org_id, status="canceled")
    r = await deliver(anon_client, event("customer.subscription.deleted", obj))
    assert r.status_code == 200
    sub = await _sub(session_factory, org_id)
    assert sub.status is SubscriptionStatus.canceled
    assert sub.plan_id == "free"


async def test_older_event_never_overwrites_a_newer_one(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    org_id = await _team_org(client)
    now = int(time.time())
    newer = event("customer.subscription.updated", subscription_obj(org_id), created=now)
    older = event(
        "invoice.payment_failed",
        {"id": "in_1", "object": "invoice", "customer": "cus_123", "subscription": "sub_123"},
        created=now - 60,
    )
    assert (await deliver(anon_client, newer)).json()["outcome"] == "applied"
    r = await deliver(anon_client, older)
    assert r.json()["outcome"] == "stale"
    assert (await _sub(session_factory, org_id)).status is SubscriptionStatus.active
    # The stale event is still recorded, so its redelivery is a duplicate, not re-evaluated.
    assert (await deliver(anon_client, older)).json()["outcome"] == "duplicate"


async def test_downgrade_below_current_usage_is_audited(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    """§6.3: allowed, but leaves an audit event; new invites refuse until back within cap."""
    org_id = await _team_org(client)
    for i in range(3):
        r = await client.post(
            "/orgs/acme/invitations", json={"email": f"u{i}@example.com", "role": "member"}
        )
        assert r.status_code == 201
    # team → free (1 seat) while 1 member + 3 pending invites.
    obj = subscription_obj(org_id, status="canceled")
    await deliver(anon_client, event("customer.subscription.deleted", obj))
    (row,) = await _audit(session_factory, "plan.over_cap")
    assert row.organization_id == org_id
    assert row.detail["plan_id"] == "free"
    assert row.detail["seats_used"] == 4 and row.detail["seats_cap"] == 1
    r = await client.post(
        "/orgs/acme/invitations", json={"email": "x@example.com", "role": "member"}
    )
    assert r.status_code == 402


# -- invoice.payment_failed + past_due behaviour (C.5) --------------------------------------


@pytest.mark.parametrize("shape", ["classic", "parent"])
async def test_payment_failed_marks_the_subscription_past_due(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
    shape: str,
) -> None:
    """Older API versions put the subscription id on the invoice; newer ones under `parent`."""
    org_id = await _team_org(client)
    await _set_sub(
        session_factory, org_id, stripe_customer_id="cus_123", stripe_subscription_id="sub_123"
    )
    invoice: dict[str, Any] = {"id": "in_1", "object": "invoice", "customer": "cus_123"}
    if shape == "classic":
        invoice["subscription"] = "sub_123"
    else:
        invoice["parent"] = {
            "type": "subscription_details",
            "subscription_details": {"subscription": "sub_123", "metadata": {}},
        }
    r = await deliver(anon_client, event("invoice.payment_failed", invoice))
    assert r.json()["outcome"] == "applied", r.text
    sub = await _sub(session_factory, org_id)
    assert sub.status is SubscriptionStatus.past_due
    assert sub.plan_id == "team"  # the plan stays; only new growth is blocked


async def test_past_due_blocks_new_seats_and_projects_but_not_existing_work(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org_id = await _team_org(client)
    invite = await client.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    assert invite.status_code == 201
    await _set_sub(session_factory, org_id, status=SubscriptionStatus.past_due)

    r = await client.post(
        "/orgs/acme/invitations", json={"email": "c@example.com", "role": "member"}
    )
    assert r.status_code == 402, r.text
    assert r.json()["code"] == "subscription_past_due"
    assert r.json()["details"][0]["organization_slug"] == "acme"

    bob = await client_for("bob@example.com")
    r = await bob.post("/orgs/invitations/accept", json={"token": invite.json()["token"]})
    assert r.status_code == 402
    assert r.json()["code"] == "subscription_past_due"

    # POST /projects creates in the caller's personal org (uncapped 'enterprise' in tests).
    assert (await client.post("/projects", json={"name": "Before"})).status_code == 201
    personal = next(
        o for o in (await client.get("/orgs")).json()["items"] if o["kind"] == "personal"
    )
    personal_id = uuid.UUID(personal["id"])
    await _set_sub(session_factory, personal_id, status=SubscriptionStatus.past_due)
    r = await client.post("/projects", json={"name": "New"})
    assert r.status_code == 402, r.text
    assert r.json()["code"] == "subscription_past_due"
    # ...even on an uncapped plan: past_due is about money, not the cap.
    assert (await client.get("/projects")).status_code == 200

    # Existing operations continue: reading the org and its plan still works.
    assert (await client.get("/orgs/acme")).status_code == 200
    plan = (await client.get("/orgs/acme/plan")).json()
    assert plan["subscription"]["status"] == "past_due"

    denials = [
        a
        for a in await _audit(session_factory, "quota.denied")
        if a.organization_id in (org_id, personal_id)
    ]
    assert {a.detail["resource"] for a in denials} == {"seats", "projects"}
    assert {a.detail["reason"] for a in denials} == {"past_due"}


async def test_concurrent_redeliveries_apply_once(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    """Stripe can deliver the same event to several workers at once; the row lock serializes
    them, so exactly one applies and the rest see a duplicate."""
    import asyncio

    org_id = await _team_org(client)
    evt = event("checkout.session.completed", checkout_completed(org_id))
    results = await asyncio.gather(*(deliver(anon_client, evt) for _ in range(4)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert sorted(r.json()["outcome"] for r in results) == ["applied"] + ["duplicate"] * 3
    assert len(await _audit(session_factory, "billing.stripe_event")) == 1


async def test_incomplete_subscription_does_not_unlock_the_paid_plan(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    """`incomplete` = the first payment has not gone through; the plan must not move yet."""
    org_id = await _team_org(client)
    obj = subscription_obj(org_id, status="incomplete", price="price_business")
    r = await deliver(anon_client, event("customer.subscription.created", obj))
    assert r.status_code == 200
    sub = await _sub(session_factory, org_id)
    assert sub.plan_id == "team"
    assert sub.stripe_subscription_id == "sub_123"


async def test_events_from_a_replaced_subscription_do_not_touch_the_live_one(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,
) -> None:
    """Org canceled sub_old, then bought sub_new. A late sub_old event must not downgrade it."""
    org_id = await _team_org(client)
    await _set_sub(
        session_factory,
        org_id,
        plan_id="business",
        status=SubscriptionStatus.active,
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_new",
    )
    old = subscription_obj(org_id, status="canceled", sub_id="sub_old")
    r = await deliver(anon_client, event("customer.subscription.deleted", old))
    assert r.json()["outcome"] == "other_subscription"
    failed = {"id": "in_9", "object": "invoice", "customer": "cus_123", "subscription": "sub_old"}
    r = await deliver(anon_client, event("invoice.payment_failed", failed))
    assert r.json()["outcome"] == "other_subscription"
    sub = await _sub(session_factory, org_id)
    assert (sub.plan_id, sub.status) == ("business", SubscriptionStatus.active)
    assert sub.stripe_subscription_id == "sub_new"


# -- review F-004: signed events that aren't shaped like Stripe events ---------------------------


@pytest.mark.usefixtures("webhook_configured")
@pytest.mark.parametrize(
    "mangle",
    [
        {"data": {"object": "x"}},
        {"data": {"object": ["a"]}},
        {"data": None},
        {"data": []},
        {"data": "x"},
    ],
)
async def test_signed_but_malformed_event_is_acknowledged_not_a_500(
    anon_client: AsyncClient, mangle: dict[str, Any]
) -> None:
    evt = {**event("customer.subscription.updated", {"id": "sub_x"}), **mangle}
    r = await deliver(anon_client, evt)
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "ignored"
