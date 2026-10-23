"""Multi-tenancy with Keycloak organizations (generated): each organization is a tenant, and one
tenant's rows are invisible to every other tenant."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth import config
from app.db import session_factory
from app.models.customers import Customer
from app.models.deals import Deal
from tests import _factories
from tests._auth_support import (
    ALL_ROLES,
    bearer,
    client_for,
    sign_in,
    token,
)

pytestmark = pytest.mark.usefixtures("outbox")


async def test_a_user_without_an_organization_is_refused(client: AsyncClient) -> None:
    response = await client.get("/auth/me", headers=bearer(token(organization=None)))

    assert response.status_code == 403
    assert response.json()["code"] == "no_organization"


async def test_a_user_in_several_organizations_must_pick_one(client: AsyncClient) -> None:
    both = token(organization=["acme", "globex"])

    response = await client.get("/auth/me", headers=bearer(both))

    assert response.status_code == 403
    assert response.json()["code"] == "organization_required"


async def test_the_tenant_is_the_organization(client: AsyncClient) -> None:
    async with client_for(await sign_in(client, "founder@example.com")) as http:
        me = (await http.get("/auth/me")).json()
        tenant = (await http.get("/auth/tenant")).json()

    assert tenant["name"] == "org-founder-at-example.com"
    assert tenant["id"] == me["tenant_id"]
    # Derived from the alias, so the same in every environment.
    assert tenant["id"] == str(uuid.uuid5(config.TENANT_NAMESPACE, tenant["name"]))


async def test_people_of_one_organization_share_a_tenant(client: AsyncClient) -> None:
    async with client_for(await sign_in(client, "a@example.com")) as a:
        first = (await a.get("/auth/tenant")).json()
    async with client_for(await sign_in(client, "b@example.com", join="a@example.com")) as b:
        second = (await b.get("/auth/tenant")).json()
    async with client_for(await sign_in(client, "c@example.com")) as c:
        other = (await c.get("/auth/tenant")).json()

    assert first["id"] == second["id"]
    assert first["id"] != other["id"]


async def test_the_organization_object_form_is_understood(client: AsyncClient) -> None:
    as_object = token(organization={"acme": {"id": str(uuid.uuid4())}})

    response = await client.get("/auth/tenant", headers=bearer(as_object))

    assert response.status_code == 200
    assert response.json()["name"] == "acme"


async def test_a_user_who_changes_organization_changes_tenant(client: AsyncClient) -> None:
    sub = uuid.uuid4()
    first = await client.get("/auth/tenant", headers=bearer(token(sub=sub, organization=["acme"])))
    second = await client.get("/auth/tenant", headers=bearer(token(sub=sub, organization=["globex"])))

    assert first.json()["name"] == "acme" and second.json()["name"] == "globex"
    assert first.json()["id"] != second.json()["id"]


async def test_customers_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES))
    colleague_headers = await sign_in(
        client, "colleague@example.com", roles=list(ALL_ROLES), join="a@example.com"
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


async def test_deals_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES))
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
    ):
        created = await _factories.make_deals(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Deal.tenant_id).where(Deal.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/deals")).json()["total"] == 0

        assert (await tenant_b.get(f"/deals/{item_id}")).status_code == 404
        assert (await tenant_b.head(f"/deals/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/deals/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/deals/{item_id}")).status_code == 204
