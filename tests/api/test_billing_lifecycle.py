"""Backend gaps A–C, section 4: billing lifecycle (trials, reconciliation, livemode)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.core import platform_security as sec
from app.models.enums import PlatformRole, SubscriptionStatus
from app.models.platform import AuditLog, Subscription
from app.services import billing_reconcile, stripe_client
from tests.api.conftest import ClientFor
from tests.api.test_billing_webhooks import (  # reuse agent 3's signed-event helpers
    deliver,
    event,
    subscription_obj,
    webhook_configured,  # noqa: F401  (fixture)
)

Factory = async_sessionmaker[AsyncSession]


async def _team_org(client: AsyncClient) -> uuid.UUID:
    r = await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201
    return uuid.UUID(r.json()["id"])


async def _set(factory: Factory, org_id: uuid.UUID, **fields: Any) -> None:
    async with factory() as session:
        sub = await session.get(Subscription, org_id)
        assert sub is not None
        for k, v in fields.items():
            setattr(sub, k, v)
        await session.commit()


async def _sub(factory: Factory, org_id: uuid.UUID) -> Subscription:
    async with factory() as session:
        sub = await session.get(Subscription, org_id)
        assert sub is not None
        return sub


# -- trials --------------------------------------------------------------------------------


async def test_an_expired_platform_trial_falls_back_to_free(
    client: AsyncClient, session_factory: Factory
) -> None:
    """A trial with no Stripe subscription behind it ends on its date: the org drops to the
    free plan (soft-fail: nothing is deleted; new growth is refused past the free caps)."""
    org = await _team_org(client)
    await _set(
        session_factory,
        org,
        status=SubscriptionStatus.trial,
        trial_ends_at=datetime.now(UTC) - timedelta(hours=1),
    )
    r = await client.post("/projects", json={"name": "One", "organization_id": str(org)})
    assert r.status_code == 201  # free allows one project
    r = await client.post("/projects", json={"name": "Two", "organization_id": str(org)})
    assert r.status_code == 402
    assert r.json()["details"][0]["plan"] == "free"
    sub = await _sub(session_factory, org)
    assert (sub.plan_id, sub.status) == ("free", SubscriptionStatus.canceled)
    async with session_factory() as session:
        audited = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "billing.trial_expired")
            )
        ).scalar_one()
        assert audited.organization_id == org


async def test_plan_page_shows_the_expired_trial_as_free(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await _team_org(client)
    await _set(
        session_factory,
        org,
        status=SubscriptionStatus.trial,
        trial_ends_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    body = (await client.get("/orgs/acme/plan")).json()
    assert body["plan"]["id"] == "free"
    assert body["subscription"]["status"] == "canceled"


async def test_a_running_trial_is_left_alone(client: AsyncClient, session_factory: Factory) -> None:
    org = await _team_org(client)
    await _set(
        session_factory,
        org,
        status=SubscriptionStatus.trial,
        trial_ends_at=datetime.now(UTC) + timedelta(days=3),
    )
    assert (await client.get("/orgs/acme/plan")).json()["plan"]["id"] == "team"


async def test_stripe_trials_are_left_to_stripe(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await _team_org(client)
    await _set(
        session_factory,
        org,
        status=SubscriptionStatus.trial,
        trial_ends_at=datetime.now(UTC) - timedelta(hours=1),
        stripe_customer_id="cus_1",
        stripe_subscription_id="sub_1",
    )
    assert (await client.get("/orgs/acme/plan")).json()["plan"]["id"] == "team"


# -- reconciliation ----------------------------------------------------------------------------


@pytest.fixture
def stripe_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUILDER_STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv(
        "BUILDER_STRIPE_PRICE_IDS", '{"team": "price_team", "business": "price_business"}'
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_reconcile_applies_what_a_missed_webhook_would_have(
    client: AsyncClient,
    session_factory: Factory,
    stripe_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = await _team_org(client)
    await _set(session_factory, org, stripe_customer_id="cus_123", stripe_subscription_id="sub_123")

    async def fake_fetch(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["subscription_id"] == "sub_123"
        return subscription_obj(org, status="past_due", price="price_business")

    monkeypatch.setattr(stripe_client, "fetch_subscription", fake_fetch)
    async with session_factory() as session:
        report = await billing_reconcile.reconcile(session)
    assert report.checked == 1 and report.changed == 1 and report.failed == 0
    sub = await _sub(session_factory, org)
    assert (sub.plan_id, sub.status) == ("business", SubscriptionStatus.past_due)

    # A second pass finds nothing to change and writes no audit row.
    async with session_factory() as session:
        again = await billing_reconcile.reconcile(session)
    assert again.changed == 0
    async with session_factory() as session:
        rows = (
            await session.execute(select(AuditLog).where(AuditLog.action == "billing.reconciled"))
        ).scalars()
        assert len(list(rows)) == 1


async def test_reconcile_keeps_going_when_one_org_fails(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: Factory,
    stripe_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = await _team_org(client)
    other = await client_for("other@example.com")
    b = uuid.UUID((await other.post("/orgs", json={"name": "B", "slug": "bee"})).json()["id"])
    await _set(session_factory, a, stripe_customer_id="cus_a", stripe_subscription_id="sub_a")
    await _set(session_factory, b, stripe_customer_id="cus_b", stripe_subscription_id="sub_b")

    async def fake_fetch(**kwargs: Any) -> dict[str, Any]:
        if kwargs["subscription_id"] == "sub_a":
            raise stripe_client.StripeError("boom")
        return subscription_obj(
            b, status="active", price="price_business", sub_id="sub_b", customer="cus_b"
        )

    monkeypatch.setattr(stripe_client, "fetch_subscription", fake_fetch)
    async with session_factory() as session:
        report = await billing_reconcile.reconcile(session)
    assert (report.checked, report.changed, report.failed) == (2, 1, 1)
    assert (await _sub(session_factory, b)).plan_id == "business"


async def test_operator_can_run_reconciliation(
    client_for: ClientFor, stripe_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = await client_for(
        "ops@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )
    r = await ops.post("/admin/billing/reconcile")
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"checked", "changed", "failed", "trials_expired"}


async def test_reconcile_without_stripe_only_expires_trials(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BUILDER_STRIPE_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    org = await _team_org(client)
    await _set(
        session_factory,
        org,
        status=SubscriptionStatus.trial,
        trial_ends_at=datetime.now(UTC) - timedelta(hours=1),
    )
    async with session_factory() as session:
        report = await billing_reconcile.reconcile(session)
    assert report.trials_expired == 1 and report.checked == 0
    get_settings.cache_clear()


# -- livemode -------------------------------------------------------------------------------


async def test_live_events_are_ignored_by_a_test_mode_platform(
    anon_client: AsyncClient,
    client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,  # noqa: F811
) -> None:
    org = await _team_org(client)
    evt = event("customer.subscription.updated", subscription_obj(org, status="active"))
    evt["livemode"] = True  # sk_test_ key configured → this event is from the other mode
    r = await deliver(anon_client, evt)
    assert r.status_code == 200
    assert (await _sub(session_factory, org)).plan_id == "team"
    async with session_factory() as session:
        row = (
            await session.execute(select(AuditLog).where(AuditLog.target_id == evt["id"]))
        ).scalar_one()
        assert row.detail["outcome"] == "livemode_mismatch"
