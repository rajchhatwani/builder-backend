"""Multi-tenancy tests (generated): a tenant's users, invitations and rows are invisible to
every other tenant."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth import config
from app.db import session_factory
from app.models.announcements import Announcement
from app.models.labels import Label
from app.models.tasks import Task
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


async def test_tasks_cannot_point_at_another_tenants_announcements(
    client: AsyncClient,
) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    async with client_for(a_headers) as tenant_a, client_for(b_headers) as tenant_b:
        foreign = await _factories.make_announcements(tenant_b)
        own = await _factories.make_announcements(tenant_a)
        payload = await _factories.payload_tasks(tenant_a, announcement_id=own["id"])

        foreign_ref = {"announcement_id": foreign["id"]}

        refused = await tenant_a.post("/tasks", json={**payload, **foreign_ref})
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "invalid_reference"

        created = await tenant_a.post("/tasks", json=payload)
        assert created.status_code == 201, created.text
        item_id = created.json()["id"]

        moved = await tenant_a.patch(f"/tasks/{item_id}", json=foreign_ref)
        assert moved.status_code == 422, moved.text
        assert moved.json()["code"] == "invalid_reference"

        replaced = await tenant_a.put(f"/tasks/{item_id}", json={**payload, **foreign_ref})
        assert replaced.status_code == 422, replaced.text


async def test_labels_cannot_link_another_tenants_tasks(
    client: AsyncClient,
) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    async with client_for(a_headers) as tenant_a, client_for(b_headers) as tenant_b:
        foreign = await _factories.make_tasks(tenant_b)
        own = await _factories.make_tasks(tenant_a)
        payload = await _factories.payload_labels(tenant_a)

        refused = await tenant_a.post(
            "/labels", json={**payload, "tasks": [own["id"], foreign["id"]]}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "invalid_reference"

        linked = await tenant_a.post("/labels", json={**payload, "tasks": [own["id"]]})
        assert linked.status_code == 201, linked.text


async def test_tasks_cannot_link_another_tenants_labels(
    client: AsyncClient,
) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    async with client_for(a_headers) as tenant_a, client_for(b_headers) as tenant_b:
        foreign = await _factories.make_labels(tenant_b)
        own = await _factories.make_labels(tenant_a)
        payload = await _factories.payload_tasks(tenant_a)

        refused = await tenant_a.post(
            "/tasks", json={**payload, "labels": [own["id"], foreign["id"]]}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "invalid_reference"

        linked = await tenant_a.post("/tasks", json={**payload, "labels": [own["id"]]})
        assert linked.status_code == 201, linked.text


async def test_announcements_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
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
        created = await _factories.make_announcements(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Announcement.tenant_id).where(Announcement.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/announcements")).json()["total"] == 0
        assert (await colleague.get("/announcements")).json()["total"] == 1

        assert (await tenant_b.get(f"/announcements/{item_id}")).status_code == 404
        assert (await colleague.get(f"/announcements/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/announcements/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/announcements/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/announcements/{item_id}")).status_code == 204


async def test_labels_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
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
        created = await _factories.make_labels(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Label.tenant_id).where(Label.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/labels")).json()["total"] == 0
        assert (await colleague.get("/labels")).json()["total"] == 1

        assert (await tenant_b.get(f"/labels/{item_id}")).status_code == 404
        assert (await colleague.get(f"/labels/{item_id}")).status_code == 200
        assert (await tenant_b.head(f"/labels/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/labels/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/labels/{item_id}")).status_code == 204


async def test_tasks_rows_stay_inside_their_tenant(client: AsyncClient) -> None:
    a_headers = await sign_in(client, "a@example.com", roles=list(ALL_ROLES))
    b_headers = await sign_in(client, "b@example.com", roles=list(ALL_ROLES), n=1)
    async with (
        client_for(a_headers) as tenant_a,
        client_for(b_headers) as tenant_b,
    ):
        created = await _factories.make_tasks(tenant_a)
        item_id = created["id"]

        me = (await tenant_a.get("/auth/me")).json()
        async with session_factory() as session:
            stamped = (
                await session.execute(
                    select(Task.tenant_id).where(Task.id == uuid.UUID(item_id))
                )
            ).scalar_one()
        assert str(stamped) == me["tenant_id"], "new rows are stamped with the creator's tenant"

        assert (await tenant_b.get("/tasks")).json()["total"] == 0

        assert (await tenant_b.get(f"/tasks/{item_id}")).status_code == 404
        assert (await tenant_b.head(f"/tasks/{item_id}")).status_code == 404

        assert (await tenant_b.delete(f"/tasks/{item_id}")).status_code == 404
        assert (await tenant_a.delete(f"/tasks/{item_id}")).status_code == 204
