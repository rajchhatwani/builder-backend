"""Multi-tenancy tests (generated): a tenant's users, invitations and rows are invisible to
every other tenant."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth import config
from app.db import session_factory
from app.models.articles import Article
from app.models.blogs import Blog
from app.models.cart_lines import CartLine
from app.models.carts import Cart
from app.models.collections import Collection
from app.models.customer_addresses import CustomerAddress
from app.models.customers import Customer
from app.models.discount_usages import DiscountUsage
from app.models.discounts import Discount
from app.models.fulfillment_lines import FulfillmentLine
from app.models.fulfillments import Fulfillment
from app.models.gift_cards import GiftCard
from app.models.inventory_levels import InventoryLevel
from app.models.locations import Location
from app.models.metafields import Metafield
from app.models.order_events import OrderEvent
from app.models.order_lines import OrderLine
from app.models.orders import Order
from app.models.pages import Page
from app.models.product_images import ProductImage
from app.models.products import Product
from app.models.refund_lines import RefundLine
from app.models.refunds import Refund
from app.models.reviews import Review
from app.models.shipping_rates import ShippingRate
from app.models.shipping_zones import ShippingZone
from app.models.stores import Store
from app.models.tags import Tag
from app.models.tax_rates import TaxRate
from app.models.transactions import Transaction
from app.models.variants import Variant
from app.models.webhooks import Webhook
from tests import _factories
from tests._auth_support import (
    ALL_ROLES,
    Outbox,
    client_for,
    registration_payload,
    sign_in,
)

# The `outbox` fixture (tests/_auth_support.py) sets the test secrets and captures mail / SMS.
pytestmark = pytest.mark.usefixtures("outbox")


async def test_signing_up_needs_a_tenant_name_or_an_invitation(client: AsyncClient) -> None:
    payload = await registration_payload("nobody@example.com")
    payload.pop("tenant_name")

    response = await client.post("/auth/register", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "tenant_required"


async def test_the_first_user_creates_a_tenant_and_becomes_its_admin(client: AsyncClient) -> None:
    async with client_for(await sign_in(client, "founder@example.com")) as founder:
        me = (await founder.get("/auth/me")).json()
        tenant = (await founder.get("/auth/tenant")).json()

    assert tenant["name"] == "Tenant of founder@example.com"
    assert me["tenant_id"] == tenant["id"]
    assert config.ADMIN_ROLE in me["roles"]


async def test_every_sign_up_gets_its_own_tenant(client: AsyncClient) -> None:
    async with client_for(await sign_in(client, "one@example.com")) as one:
        first = (await one.get("/auth/tenant")).json()
    async with client_for(await sign_in(client, "two@example.com", n=1)) as two:
        second = (await two.get("/auth/tenant")).json()

    assert first["id"] != second["id"]


async def test_an_invitation_joins_the_inviters_tenant(
    client: AsyncClient, outbox: Outbox
) -> None:
    async with client_for(await sign_in(client, "boss@example.com")) as boss:
        tenant = (await boss.get("/auth/tenant")).json()
        invited = await boss.post("/auth/invitations", json={"email": "hire@example.com"})
        assert invited.status_code == 201, invited.text
        token = outbox.link_token()

    payload = await registration_payload("hire@example.com", n=1)
    payload["invite_token"] = token
    registered = await client.post("/auth/register", json=payload)

    assert registered.status_code == 201, registered.text
    body = registered.json()
    assert body["tenant_id"] == tenant["id"]
    # Joining a tenant does not make you its admin.
    assert (config.ADMIN_ROLE in body["roles"]) == (config.ADMIN_ROLE in config.DEFAULT_ROLES)


async def test_invitations_are_private_to_their_tenant(
    client: AsyncClient, outbox: Outbox
) -> None:
    async with (
        client_for(await sign_in(client, "a-admin@example.com")) as tenant_a,
        client_for(await sign_in(client, "b-admin@example.com", n=1)) as tenant_b,
    ):
        sent = await tenant_a.post("/auth/invitations", json={"email": "guest@example.com"})
        assert sent.status_code == 201, sent.text
        invitation_id = sent.json()["id"]

        assert [i["email"] for i in (await tenant_a.get("/auth/invitations")).json()] == [
            "guest@example.com"
        ]
        assert (await tenant_b.get("/auth/invitations")).json() == []
        # Another tenant's admin cannot even tell that the invitation exists.
        assert (await tenant_b.delete(f"/auth/invitations/{invitation_id}")).status_code == 404
        assert (await tenant_a.delete(f"/auth/invitations/{invitation_id}")).status_code == 204


async def test_articles_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_articles(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Article.tenant_id).where(Article.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/articles")).json()["total"] == 0
        assert (await colleague.get("/articles")).json()["total"] == 1

        assert (await tenant_b.get(f"/articles/{item_id}")).status_code == 404
        assert (await colleague.get(f"/articles/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/articles/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/articles/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/articles/{item_id}")).status_code == 204


async def test_blogs_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_blogs(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Blog.tenant_id).where(Blog.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/blogs")).json()["total"] == 0
        assert (await colleague.get("/blogs")).json()["total"] == 1

        assert (await tenant_b.get(f"/blogs/{item_id}")).status_code == 404
        assert (await colleague.get(f"/blogs/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/blogs/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/blogs/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/blogs/{item_id}")).status_code == 204


async def test_cart_lines_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_cart_lines(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(CartLine.tenant_id).where(CartLine.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/cart_lines")).json()["total"] == 0
        assert (await colleague.get("/cart_lines")).json()["total"] == 1

        assert (await tenant_b.get(f"/cart_lines/{item_id}")).status_code == 404
        assert (await colleague.get(f"/cart_lines/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/cart_lines/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/cart_lines/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/cart_lines/{item_id}")).status_code == 204


async def test_carts_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_carts(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Cart.tenant_id).where(Cart.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/carts")).json()["total"] == 0
        assert (await colleague.get("/carts")).json()["total"] == 1

        assert (await tenant_b.get(f"/carts/{item_id}")).status_code == 404
        assert (await colleague.get(f"/carts/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/carts/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/carts/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/carts/{item_id}")).status_code == 204


async def test_collections_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_collections(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Collection.tenant_id).where(Collection.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/collections")).json()["total"] == 0
        assert (await colleague.get("/collections")).json()["total"] == 1

        assert (await tenant_b.get(f"/collections/{item_id}")).status_code == 404
        assert (await colleague.get(f"/collections/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/collections/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/collections/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/collections/{item_id}")).status_code == 204


async def test_customer_addresses_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_customer_addresses(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(CustomerAddress.tenant_id).where(CustomerAddress.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/customer_addresses")).json()["total"] == 0
        assert (await colleague.get("/customer_addresses")).json()["total"] == 1

        assert (await tenant_b.get(f"/customer_addresses/{item_id}")).status_code == 404
        assert (await colleague.get(f"/customer_addresses/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/customer_addresses/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/customer_addresses/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/customer_addresses/{item_id}")).status_code == 204


async def test_customers_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_customers(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Customer.tenant_id).where(Customer.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/customers")).json()["total"] == 0
        assert (await colleague.get("/customers")).json()["total"] == 1

        assert (await tenant_b.get(f"/customers/{item_id}")).status_code == 404
        assert (await colleague.get(f"/customers/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/customers/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/customers/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/customers/{item_id}")).status_code == 204


async def test_discount_usages_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_discount_usages(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(DiscountUsage.tenant_id).where(DiscountUsage.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/discount_usages")).json()["total"] == 0
        assert (await colleague.get("/discount_usages")).json()["total"] == 1

        assert (await tenant_b.get(f"/discount_usages/{item_id}")).status_code == 404
        assert (await colleague.get(f"/discount_usages/{item_id}")).status_code == 200


async def test_discounts_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_discounts(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Discount.tenant_id).where(Discount.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/discounts")).json()["total"] == 0
        assert (await colleague.get("/discounts")).json()["total"] == 1

        assert (await tenant_b.get(f"/discounts/{item_id}")).status_code == 404
        assert (await colleague.get(f"/discounts/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/discounts/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/discounts/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/discounts/{item_id}")).status_code == 204


async def test_fulfillment_lines_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_fulfillment_lines(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(FulfillmentLine.tenant_id).where(FulfillmentLine.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/fulfillment_lines")).json()["total"] == 0
        assert (await colleague.get("/fulfillment_lines")).json()["total"] == 1

        assert (await tenant_b.get(f"/fulfillment_lines/{item_id}")).status_code == 404
        assert (await colleague.get(f"/fulfillment_lines/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/fulfillment_lines/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/fulfillment_lines/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/fulfillment_lines/{item_id}")).status_code == 204


async def test_fulfillments_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_fulfillments(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Fulfillment.tenant_id).where(Fulfillment.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/fulfillments")).json()["total"] == 0
        assert (await colleague.get("/fulfillments")).json()["total"] == 1

        assert (await tenant_b.get(f"/fulfillments/{item_id}")).status_code == 404
        assert (await colleague.get(f"/fulfillments/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/fulfillments/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/fulfillments/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/fulfillments/{item_id}")).status_code == 204


async def test_gift_cards_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_gift_cards(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(GiftCard.tenant_id).where(GiftCard.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/gift_cards")).json()["total"] == 0
        assert (await colleague.get("/gift_cards")).json()["total"] == 1

        assert (await tenant_b.get(f"/gift_cards/{item_id}")).status_code == 404
        assert (await colleague.get(f"/gift_cards/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/gift_cards/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/gift_cards/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/gift_cards/{item_id}")).status_code == 204


async def test_inventory_levels_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_inventory_levels(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(InventoryLevel.tenant_id).where(InventoryLevel.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/inventory_levels")).json()["total"] == 0
        assert (await colleague.get("/inventory_levels")).json()["total"] == 1

        assert (await tenant_b.get(f"/inventory_levels/{item_id}")).status_code == 404
        assert (await colleague.get(f"/inventory_levels/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/inventory_levels/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/inventory_levels/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/inventory_levels/{item_id}")).status_code == 204


async def test_locations_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_locations(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Location.tenant_id).where(Location.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/locations")).json()["total"] == 0
        assert (await colleague.get("/locations")).json()["total"] == 1

        assert (await tenant_b.get(f"/locations/{item_id}")).status_code == 404
        assert (await colleague.get(f"/locations/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/locations/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/locations/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/locations/{item_id}")).status_code == 204


async def test_metafields_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_metafields(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Metafield.tenant_id).where(Metafield.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/metafields")).json()["total"] == 0
        assert (await colleague.get("/metafields")).json()["total"] == 1

        assert (await tenant_b.get(f"/metafields/{item_id}")).status_code == 404
        assert (await colleague.get(f"/metafields/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/metafields/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/metafields/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/metafields/{item_id}")).status_code == 204


async def test_order_events_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_order_events(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(OrderEvent.tenant_id).where(OrderEvent.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/order_events")).json()["total"] == 0
        assert (await colleague.get("/order_events")).json()["total"] == 1

        assert (await tenant_b.get(f"/order_events/{item_id}")).status_code == 404
        assert (await colleague.get(f"/order_events/{item_id}")).status_code == 200


async def test_order_lines_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_order_lines(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(OrderLine.tenant_id).where(OrderLine.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/order_lines")).json()["total"] == 0
        assert (await colleague.get("/order_lines")).json()["total"] == 1

        assert (await tenant_b.get(f"/order_lines/{item_id}")).status_code == 404
        assert (await colleague.get(f"/order_lines/{item_id}")).status_code == 200


async def test_orders_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_orders(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Order.tenant_id).where(Order.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/orders")).json()["total"] == 0
        assert (await colleague.get("/orders")).json()["total"] == 1

        assert (await tenant_b.get(f"/orders/{item_id}")).status_code == 404
        assert (await colleague.get(f"/orders/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/orders/{item_id}")).status_code == 404


async def test_pages_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_pages(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Page.tenant_id).where(Page.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/pages")).json()["total"] == 0
        assert (await colleague.get("/pages")).json()["total"] == 1

        assert (await tenant_b.get(f"/pages/{item_id}")).status_code == 404
        assert (await colleague.get(f"/pages/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/pages/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/pages/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/pages/{item_id}")).status_code == 204


async def test_product_images_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_product_images(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(ProductImage.tenant_id).where(ProductImage.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/product_images")).json()["total"] == 0
        assert (await colleague.get("/product_images")).json()["total"] == 1

        assert (await tenant_b.get(f"/product_images/{item_id}")).status_code == 404
        assert (await colleague.get(f"/product_images/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/product_images/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/product_images/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/product_images/{item_id}")).status_code == 204


async def test_products_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_products(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Product.tenant_id).where(Product.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/products")).json()["total"] == 0
        assert (await colleague.get("/products")).json()["total"] == 1

        assert (await tenant_b.get(f"/products/{item_id}")).status_code == 404
        assert (await colleague.get(f"/products/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/products/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/products/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/products/{item_id}")).status_code == 204


async def test_refund_lines_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_refund_lines(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(RefundLine.tenant_id).where(RefundLine.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/refund_lines")).json()["total"] == 0
        assert (await colleague.get("/refund_lines")).json()["total"] == 1

        assert (await tenant_b.get(f"/refund_lines/{item_id}")).status_code == 404
        assert (await colleague.get(f"/refund_lines/{item_id}")).status_code == 200


async def test_refunds_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_refunds(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Refund.tenant_id).where(Refund.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/refunds")).json()["total"] == 0
        assert (await colleague.get("/refunds")).json()["total"] == 1

        assert (await tenant_b.get(f"/refunds/{item_id}")).status_code == 404
        assert (await colleague.get(f"/refunds/{item_id}")).status_code == 200


async def test_reviews_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_reviews(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Review.tenant_id).where(Review.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/reviews")).json()["total"] == 0
        assert (await colleague.get("/reviews")).json()["total"] == 1

        assert (await tenant_b.get(f"/reviews/{item_id}")).status_code == 404
        assert (await colleague.get(f"/reviews/{item_id}")).status_code == 200

        assert (await tenant_b.delete(f"/reviews/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/reviews/{item_id}")).status_code == 204


async def test_shipping_rates_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_shipping_rates(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(ShippingRate.tenant_id).where(ShippingRate.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/shipping_rates")).json()["total"] == 0
        assert (await colleague.get("/shipping_rates")).json()["total"] == 1

        assert (await tenant_b.get(f"/shipping_rates/{item_id}")).status_code == 404
        assert (await colleague.get(f"/shipping_rates/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/shipping_rates/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/shipping_rates/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/shipping_rates/{item_id}")).status_code == 204


async def test_shipping_zones_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_shipping_zones(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(ShippingZone.tenant_id).where(ShippingZone.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/shipping_zones")).json()["total"] == 0
        assert (await colleague.get("/shipping_zones")).json()["total"] == 1

        assert (await tenant_b.get(f"/shipping_zones/{item_id}")).status_code == 404
        assert (await colleague.get(f"/shipping_zones/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/shipping_zones/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/shipping_zones/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/shipping_zones/{item_id}")).status_code == 204


async def test_stores_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_stores(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Store.tenant_id).where(Store.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/stores")).json()["total"] == 0
        assert (await colleague.get("/stores")).json()["total"] == 1

        assert (await tenant_b.get(f"/stores/{item_id}")).status_code == 404
        assert (await colleague.get(f"/stores/{item_id}")).status_code == 200


async def test_tags_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_tags(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Tag.tenant_id).where(Tag.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/tags")).json()["total"] == 0
        assert (await colleague.get("/tags")).json()["total"] == 1

        assert (await tenant_b.get(f"/tags/{item_id}")).status_code == 404
        assert (await colleague.get(f"/tags/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/tags/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/tags/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/tags/{item_id}")).status_code == 204


async def test_tax_rates_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_tax_rates(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(TaxRate.tenant_id).where(TaxRate.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/tax_rates")).json()["total"] == 0
        assert (await colleague.get("/tax_rates")).json()["total"] == 1

        assert (await tenant_b.get(f"/tax_rates/{item_id}")).status_code == 404
        assert (await colleague.get(f"/tax_rates/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/tax_rates/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/tax_rates/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/tax_rates/{item_id}")).status_code == 204


async def test_transactions_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_transactions(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Transaction.tenant_id).where(Transaction.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/transactions")).json()["total"] == 0
        assert (await colleague.get("/transactions")).json()["total"] == 1

        assert (await tenant_b.get(f"/transactions/{item_id}")).status_code == 404
        assert (await colleague.get(f"/transactions/{item_id}")).status_code == 200


async def test_variants_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_variants(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Variant.tenant_id).where(Variant.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/variants")).json()["total"] == 0
        assert (await colleague.get("/variants")).json()["total"] == 1

        assert (await tenant_b.get(f"/variants/{item_id}")).status_code == 404
        assert (await colleague.get(f"/variants/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/variants/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/variants/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/variants/{item_id}")).status_code == 204


async def test_webhooks_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), n=2, join="a@example.com"
    )
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
        client_for(colleague_headers) as colleague,
    ):
        created = await _factories.make_webhooks(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Webhook.tenant_id).where(Webhook.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/webhooks")).json()["total"] == 0
        assert (await colleague.get("/webhooks")).json()["total"] == 1

        assert (await tenant_b.get(f"/webhooks/{item_id}")).status_code == 404
        assert (await colleague.get(f"/webhooks/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/webhooks/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/webhooks/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/webhooks/{item_id}")).status_code == 204
