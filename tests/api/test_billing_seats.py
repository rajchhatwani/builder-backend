"""Phase C steps 1, 2 and 4 — one Stripe subscription per org, and seat sync.

- C.1/C.2: an org that already pays through a Stripe subscription is not sent through a
  second Checkout (that would create a second subscription); plan changes, card updates
  and cancellation go through the Stripe Billing Portal for the org's one Customer.
- C.4: when a member joins, the subscription item's quantity follows the seat count and
  Stripe prorates (§10). Seats are billed high-water-mark (§6.4): mid-cycle the quantity
  only goes up; a leaver is dropped from the bill at the next period. A Stripe outage never
  blocks the membership change — it is logged and audited, and the next change catches up.

Stripe is never called for real: the `stripe_client` functions are replaced by fakes.
"""

import json
import time
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.enums import SubscriptionStatus
from app.models.platform import AuditLog, Subscription
from app.services import stripe_client
from tests.api.conftest import ClientFor
from tests.api.test_billing_webhooks import deliver, event, subscription_obj

Factory = async_sessionmaker[AsyncSession]


class FakeStripe:
    def __init__(self) -> None:
        self.quantity = 1
        self.updates: list[dict[str, Any]] = []
        self.portals: list[dict[str, Any]] = []
        self.fail = False

    async def get_subscription(self, **kw: Any) -> stripe_client.SubscriptionInfo:
        if self.fail:
            raise stripe_client.StripeError("stripe 500: boom sk_test_dummy")
        return stripe_client.SubscriptionInfo(
            id=kw["subscription_id"], item_id="si_1", quantity=self.quantity
        )

    async def set_item_quantity(self, **kw: Any) -> None:
        self.updates.append(kw)
        self.quantity = kw["quantity"]

    async def create_portal_session(self, **kw: Any) -> str:
        self.portals.append(kw)
        return "https://billing.stripe.com/p/session/test_1"


@pytest.fixture
def fake_stripe(monkeypatch: pytest.MonkeyPatch) -> FakeStripe:
    monkeypatch.setenv("BUILDER_STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("BUILDER_STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    monkeypatch.setenv(
        "BUILDER_STRIPE_PRICE_IDS", '{"team": "price_team", "business": "price_business"}'
    )
    monkeypatch.setenv("BUILDER_PUBLIC_APP_URL", "https://builder.example.com")
    get_settings.cache_clear()
    fake = FakeStripe()
    monkeypatch.setattr(stripe_client, "get_subscription", fake.get_subscription)
    monkeypatch.setattr(stripe_client, "set_item_quantity", fake.set_item_quantity)
    monkeypatch.setattr(stripe_client, "create_portal_session", fake.create_portal_session)

    async def no_checkout(**kw: Any) -> stripe_client.CheckoutSession:
        raise AssertionError("checkout must not be created")

    monkeypatch.setattr(stripe_client, "create_checkout_session", no_checkout)
    yield fake
    get_settings.cache_clear()


async def _paying_team_org(
    client: AsyncClient, factory: Factory, status: SubscriptionStatus = SubscriptionStatus.active
) -> uuid.UUID:
    r = await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201
    org_id = uuid.UUID(r.json()["id"])
    async with factory() as session:
        sub = await session.get(Subscription, org_id)
        assert sub is not None
        sub.status = status
        sub.stripe_customer_id = "cus_123"
        sub.stripe_subscription_id = "sub_123"
        await session.commit()
    return org_id


async def _join(client: AsyncClient, client_for: ClientFor, email: str) -> AsyncClient:
    invite = await client.post("/orgs/acme/invitations", json={"email": email, "role": "member"})
    assert invite.status_code == 201, invite.text
    other = await client_for(email)
    r = await other.post("/orgs/invitations/accept", json={"token": invite.json()["token"]})
    assert r.status_code == 200, r.text
    return other


async def _audit(factory: Factory, action: str) -> list[AuditLog]:
    async with factory() as session:
        rows = await session.execute(select(AuditLog).where(AuditLog.action == action))
        return list(rows.scalars())


# -- C.4 seat sync ---------------------------------------------------------------------------


async def test_new_member_raises_the_billed_quantity_with_proration(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory, fake_stripe: FakeStripe
) -> None:
    org_id = await _paying_team_org(client, session_factory)
    await _join(client, client_for, "bob@example.com")

    assert len(fake_stripe.updates) == 1
    update = fake_stripe.updates[0]
    assert update["item_id"] == "si_1"
    assert update["quantity"] == 2
    assert update["proration_behavior"] == "create_prorations"
    (row,) = await _audit(session_factory, "billing.seats_synced")
    assert row.organization_id == org_id
    assert row.detail == {"stripe_subscription_id": "sub_123", "from": 1, "to": 2}


async def test_quantity_never_drops_mid_cycle(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory, fake_stripe: FakeStripe
) -> None:
    """High-water mark: Stripe already bills 5 seats this cycle; a 2nd member changes nothing."""
    await _paying_team_org(client, session_factory)
    fake_stripe.quantity = 5
    bob = await _join(client, client_for, "bob@example.com")
    assert fake_stripe.updates == []

    r = await client.delete(f"/orgs/acme/members/{bob.user.id}")  # type: ignore[attr-defined]
    assert r.status_code == 204
    assert fake_stripe.updates == []


async def test_stripe_outage_does_not_block_joining(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory, fake_stripe: FakeStripe
) -> None:
    org_id = await _paying_team_org(client, session_factory)
    fake_stripe.fail = True
    await _join(client, client_for, "bob@example.com")  # asserts 200
    (row,) = await _audit(session_factory, "billing.seat_sync_failed")
    assert row.organization_id == org_id
    assert row.result.value == "error"
    assert "sk_test" not in json.dumps(row.detail)


async def test_orgs_without_a_stripe_subscription_are_not_synced(
    client: AsyncClient, client_for: ClientFor, fake_stripe: FakeStripe
) -> None:
    r = await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201
    await _join(client, client_for, "bob@example.com")
    assert fake_stripe.updates == []


async def test_canceled_subscriptions_are_not_synced(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory, fake_stripe: FakeStripe
) -> None:
    await _paying_team_org(client, session_factory, SubscriptionStatus.canceled)
    async with session_factory() as session:
        sub = await session.get(Subscription, (await _org(client)))
        sub.plan_id = "team"  # keep seats available
        await session.commit()
    await _join(client, client_for, "bob@example.com")
    assert fake_stripe.updates == []


async def _org(client: AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.get("/orgs/acme")).json()["id"])


async def test_new_period_resets_quantity_to_current_members(
    client: AsyncClient,
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory: Factory,
    fake_stripe: FakeStripe,
) -> None:
    """At renewal the high-water mark restarts: bill the members the org has now, no proration."""
    org_id = await _paying_team_org(client, session_factory)
    fake_stripe.quantity = 4  # peak from the last cycle
    now = int(time.time())
    first = subscription_obj(org_id, price="price_team", period_end=now + 86400, quantity=4)
    await deliver(anon_client, event("customer.subscription.updated", first, created=now - 10))
    assert fake_stripe.updates == []  # first period we see: nothing to reset

    renewed = subscription_obj(org_id, price="price_team", period_end=now + 31 * 86400, quantity=4)
    r = await deliver(anon_client, event("customer.subscription.updated", renewed, created=now))
    assert r.status_code == 200, r.text
    assert len(fake_stripe.updates) == 1
    assert fake_stripe.updates[0]["quantity"] == 1  # only the owner is left
    assert fake_stripe.updates[0]["proration_behavior"] == "none"


# -- C.1 / C.2: one subscription per org, Billing Portal -------------------------------------


async def test_paying_org_is_not_sent_through_a_second_checkout(
    client: AsyncClient, session_factory: Factory, fake_stripe: FakeStripe
) -> None:
    await _paying_team_org(client, session_factory)
    r = await client.post("/orgs/acme/billing/checkout", json={"plan_id": "business"})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "already_subscribed"


async def test_canceled_org_can_check_out_again(
    client: AsyncClient,
    session_factory: Factory,
    fake_stripe: FakeStripe,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _paying_team_org(client, session_factory, SubscriptionStatus.canceled)
    calls: list[dict[str, Any]] = []

    async def fake_checkout(**kw: Any) -> stripe_client.CheckoutSession:
        calls.append(kw)
        return stripe_client.CheckoutSession(id="cs_2", url="https://checkout.stripe.com/x")

    monkeypatch.setattr(stripe_client, "create_checkout_session", fake_checkout)
    r = await client.post("/orgs/acme/billing/checkout", json={"plan_id": "business"})
    assert r.status_code == 201, r.text
    assert calls[0]["customer_id"] == "cus_123"  # same Stripe Customer, never a second one


async def test_admin_opens_the_billing_portal(
    client: AsyncClient, session_factory: Factory, fake_stripe: FakeStripe
) -> None:
    org_id = await _paying_team_org(client, session_factory)
    r = await client.post("/orgs/acme/billing/portal")
    assert r.status_code == 201, r.text
    assert r.json() == {"url": "https://billing.stripe.com/p/session/test_1"}
    call = fake_stripe.portals[0]
    assert call["customer_id"] == "cus_123"
    assert call["return_url"] == "https://builder.example.com/#/org/acme/plan"
    (row,) = await _audit(session_factory, "billing.portal_opened")
    assert row.organization_id == org_id

    plan = (await client.get("/orgs/acme/plan")).json()
    assert plan["portal_available"] is True


async def test_portal_needs_a_stripe_customer_and_an_admin(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory, fake_stripe: FakeStripe
) -> None:
    r = await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201
    r = await client.post("/orgs/acme/billing/portal")
    assert r.status_code == 409
    assert r.json()["code"] == "no_billing_account"
    assert (await client.get("/orgs/acme/plan")).json()["portal_available"] is False

    await _paying_team_org_existing(session_factory, await _org(client))
    bob = await _join(client, client_for, "bob@example.com")
    r = await bob.post("/orgs/acme/billing/portal")
    assert r.status_code == 403
    assert len(fake_stripe.portals) == 0


async def _paying_team_org_existing(factory: Factory, org_id: uuid.UUID) -> None:
    async with factory() as session:
        sub = await session.get(Subscription, org_id)
        assert sub is not None
        sub.stripe_customer_id = "cus_123"
        sub.stripe_subscription_id = "sub_123"
        await session.commit()


# -- the HTTP client functions -----------------------------------------------------------------


async def test_stripe_client_reads_and_updates_the_seat_item() -> None:
    import httpx

    seen: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode())) if request.content else {}
        seen.append((request.method, str(request.url), form))
        assert request.headers["authorization"] == "Bearer sk_test_abc"
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"id": "sub_1", "items": {"data": [{"id": "si_9", "quantity": 3}]}},
            )
        return httpx.Response(200, json={"id": "si_9", "quantity": 4})

    transport = httpx.MockTransport(handler)
    info = await stripe_client.get_subscription(
        secret_key="sk_test_abc", subscription_id="sub_1", transport=transport
    )
    assert info == stripe_client.SubscriptionInfo(id="sub_1", item_id="si_9", quantity=3)
    await stripe_client.set_item_quantity(
        secret_key="sk_test_abc",
        item_id="si_9",
        quantity=4,
        proration_behavior="create_prorations",
        transport=transport,
    )
    assert seen[0][:2] == ("GET", "https://api.stripe.com/v1/subscriptions/sub_1")
    method, url, form = seen[1]
    assert (method, url) == ("POST", "https://api.stripe.com/v1/subscription_items/si_9")
    assert form == {"quantity": "4", "proration_behavior": "create_prorations"}


async def test_stripe_client_creates_a_portal_session() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.stripe.com/v1/billing_portal/sessions"
        form = dict(httpx.QueryParams(request.content.decode()))
        assert form == {"customer": "cus_1", "return_url": "https://x/back"}
        return httpx.Response(200, json={"id": "bps_1", "url": "https://billing.stripe.com/p/1"})

    url = await stripe_client.create_portal_session(
        secret_key="sk_test_abc",
        customer_id="cus_1",
        return_url="https://x/back",
        transport=httpx.MockTransport(handler),
    )
    assert url == "https://billing.stripe.com/p/1"
