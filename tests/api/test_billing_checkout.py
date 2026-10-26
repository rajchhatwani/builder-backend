"""Phase B step 4 — Stripe Checkout (no webhooks; that's Phase C).

`POST /orgs/{slug}/billing/checkout` creates a Stripe Checkout Session for upgrading an
org to a target plan and returns the hosted URL. The plan itself does NOT change here:
per §6.3 the platform's view of the plan only moves on a Stripe event (Phase C) or by an
operator via `/admin/organizations/{id}/plan`.

Stripe is never called for real: `app.services.stripe_client.create_checkout_session` is
replaced with a fake that records its arguments.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.platform import AuditLog, Subscription
from app.services import stripe_client
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
def stripe_configured(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    monkeypatch.setenv("BUILDER_STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv(
        "BUILDER_STRIPE_PRICE_IDS", '{"team": "price_team", "business": "price_business"}'
    )
    monkeypatch.setenv("BUILDER_PUBLIC_APP_URL", "https://builder.example.com")
    get_settings.cache_clear()
    calls: list[dict[str, Any]] = []

    async def fake_create(**kwargs: Any) -> stripe_client.CheckoutSession:
        calls.append(kwargs)
        return stripe_client.CheckoutSession(
            id="cs_test_123", url="https://checkout.stripe.com/c/pay/cs_test_123"
        )

    monkeypatch.setattr(stripe_client, "create_checkout_session", fake_create)
    yield calls
    get_settings.cache_clear()


async def _team_org(client: AsyncClient) -> uuid.UUID:
    r = await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201
    return uuid.UUID(r.json()["id"])


async def test_admin_starts_checkout_for_a_paid_plan(
    client: AsyncClient,
    session_factory: Factory,
    stripe_configured: list[dict[str, Any]],
) -> None:
    org_id = await _team_org(client)
    r = await client.post("/orgs/acme/billing/checkout", json={"plan_id": "business"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body == {
        "id": "cs_test_123",
        "url": "https://checkout.stripe.com/c/pay/cs_test_123",
    }

    assert len(stripe_configured) == 1
    call = stripe_configured[0]
    assert call["price_id"] == "price_business"
    assert call["quantity"] == 1  # current seat count
    assert call["organization_id"] == org_id
    assert call["plan_id"] == "business"
    assert call["customer_id"] is None  # no Stripe customer yet
    assert call["customer_email"] == client.user.email  # type: ignore[attr-defined]
    assert call["success_url"].startswith("https://builder.example.com/#/org/acme/plan")
    assert call["cancel_url"].startswith("https://builder.example.com/#/org/acme/plan")

    # The plan does not move on a click — only on a Stripe event (Phase C) or an operator.
    async with session_factory() as session:
        sub = await session.get(Subscription, org_id)
        assert sub is not None and sub.plan_id == "team"
        audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "plan.checkout_started")
            )
        ).scalar_one()
        assert audit.organization_id == org_id
        assert audit.detail == {"plan_id": "business", "checkout_session_id": "cs_test_123"}


async def test_existing_stripe_customer_is_reused(
    client: AsyncClient,
    session_factory: Factory,
    stripe_configured: list[dict[str, Any]],
) -> None:
    org_id = await _team_org(client)
    async with session_factory() as session:
        sub = await session.get(Subscription, org_id)
        assert sub is not None
        sub.stripe_customer_id = "cus_existing"
        await session.commit()
    r = await client.post("/orgs/acme/billing/checkout", json={"plan_id": "business"})
    assert r.status_code == 201
    assert stripe_configured[0]["customer_id"] == "cus_existing"
    assert stripe_configured[0]["customer_email"] is None


async def test_members_cannot_start_checkout(
    client: AsyncClient, client_for: ClientFor, stripe_configured: list[dict[str, Any]]
) -> None:
    await _team_org(client)
    invite = await client.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    bob = await client_for("bob@example.com")
    await bob.post("/orgs/invitations/accept", json={"token": invite.json()["token"]})
    r = await bob.post("/orgs/acme/billing/checkout", json={"plan_id": "business"})
    assert r.status_code == 403
    assert stripe_configured == []


@pytest.mark.parametrize("plan_id", ["free", "enterprise", "team", "nope"])
async def test_only_purchasable_other_plans_can_be_checked_out(
    client: AsyncClient, stripe_configured: list[dict[str, Any]], plan_id: str
) -> None:
    """free (no price), enterprise (not public, sales-led), the current plan, unknown ids."""
    await _team_org(client)  # currently on 'team'
    r = await client.post("/orgs/acme/billing/checkout", json={"plan_id": plan_id})
    assert r.status_code in (404, 409, 422), r.text
    assert stripe_configured == []


async def test_checkout_is_unavailable_when_stripe_is_not_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BUILDER_STRIPE_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    await _team_org(client)
    r = await client.post("/orgs/acme/billing/checkout", json={"plan_id": "business"})
    assert r.status_code == 503
    assert r.json()["code"] == "billing_unavailable"
    get_settings.cache_clear()


async def test_stripe_failure_is_a_502_without_leaking_details(
    client: AsyncClient, stripe_configured: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(**kwargs: Any) -> stripe_client.CheckoutSession:
        raise stripe_client.StripeError("card_declined: secret detail sk_test_dummy")

    monkeypatch.setattr(stripe_client, "create_checkout_session", boom)
    await _team_org(client)
    r = await client.post("/orgs/acme/billing/checkout", json={"plan_id": "business"})
    assert r.status_code == 502
    assert "sk_test" not in r.text


# -- the HTTP client itself (form encoding + auth), without the network ----------------


async def test_stripe_client_posts_a_subscription_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["idempotency"] = request.headers.get("idempotency-key")
        seen["form"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.com/x"})

    transport = httpx.MockTransport(handler)
    org_id = uuid.uuid4()
    session = await stripe_client.create_checkout_session(
        secret_key="sk_test_abc",
        price_id="price_team",
        quantity=3,
        organization_id=org_id,
        plan_id="team",
        customer_id=None,
        customer_email="a@example.com",
        success_url="https://x/ok",
        cancel_url="https://x/cancel",
        transport=transport,
    )
    assert session == stripe_client.CheckoutSession(id="cs_1", url="https://checkout.stripe.com/x")
    assert seen["url"] == "https://api.stripe.com/v1/checkout/sessions"
    assert seen["auth"] == "Bearer sk_test_abc"
    assert seen["idempotency"]
    form = seen["form"]
    assert form["mode"] == "subscription"
    assert form["line_items[0][price]"] == "price_team"
    assert form["line_items[0][quantity]"] == "3"
    assert form["client_reference_id"] == str(org_id)
    assert form["metadata[organization_id]"] == str(org_id)
    assert form["metadata[plan_id]"] == "team"
    assert form["subscription_data[metadata][organization_id]"] == str(org_id)
    assert form["customer_email"] == "a@example.com"
    assert "customer" not in form


async def test_stripe_client_raises_on_error_status() -> None:
    import httpx

    transport = httpx.MockTransport(
        lambda request: httpx.Response(400, json={"error": {"message": "bad"}})
    )
    with pytest.raises(stripe_client.StripeError):
        await stripe_client.create_checkout_session(
            secret_key="sk_test_abc",
            price_id="price_team",
            quantity=1,
            organization_id=uuid.uuid4(),
            plan_id="team",
            customer_id="cus_1",
            customer_email=None,
            success_url="https://x/ok",
            cancel_url="https://x/cancel",
            transport=transport,
        )


async def test_plan_page_lists_purchasable_upgrades(
    client: AsyncClient, stripe_configured: list[dict[str, Any]]
) -> None:
    """The Plan page needs to know which plans have an online upgrade button."""
    await _team_org(client)  # on 'team'
    body = (await client.get("/orgs/acme/plan")).json()
    assert body["checkout_available"] is True
    assert [p["id"] for p in body["upgrades"]] == ["business"]  # not free/enterprise/current


async def test_plan_page_without_stripe_has_no_upgrades(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BUILDER_STRIPE_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    await _team_org(client)
    body = (await client.get("/orgs/acme/plan")).json()
    assert body["checkout_available"] is False
    assert body["upgrades"] == []
    get_settings.cache_clear()
