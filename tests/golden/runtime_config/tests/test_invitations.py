"""Tests for invitations and self-assignable roles (generated)."""

import pytest
from httpx import AsyncClient

from tests._auth_support import (
    Outbox,
    client_for,
    registration_payload,
    sign_in_plain,
)

# The `outbox` fixture (tests/_auth_support.py) sets the test secrets and captures mail / SMS.
pytestmark = pytest.mark.usefixtures("outbox")
INVITE_ROLE = 'admin'


async def _invite(admin: AsyncClient, email: str, outbox: Outbox, **extra: object) -> str:
    response = await admin.post("/auth/invitations", json={"email": email, **extra})
    assert response.status_code == 201, response.text
    assert outbox.emails[-1][0] == email
    return outbox.link_token()


async def test_an_invitation_lets_one_address_register(
    authed_client: AsyncClient, client: AsyncClient, outbox: Outbox
) -> None:
    token = await _invite(authed_client, "new@example.com", outbox, roles=[INVITE_ROLE])

    payload = await registration_payload("new@example.com", n=1)
    payload["invite_token"] = token
    registered = await client.post("/auth/register", json=payload)

    assert registered.status_code == 201, registered.text
    body = registered.json()
    assert INVITE_ROLE in body["roles"]
    assert body["email_verified_at"] is not None, "an invitation proves the address"
    login = await client.post(
        "/auth/login", json={"email": "new@example.com", "password": payload["password"]}
    )
    assert login.status_code == 200, login.text


async def test_an_invitation_works_once_and_only_for_its_address(
    authed_client: AsyncClient, client: AsyncClient, outbox: Outbox
) -> None:
    token = await _invite(authed_client, "invited@example.com", outbox)

    other = await registration_payload("someone-else@example.com", n=2)
    other["invite_token"] = token
    wrong_address = await client.post("/auth/register", json=other)
    assert wrong_address.status_code == 400
    assert wrong_address.json()["code"] == "invalid_invitation"

    mine = await registration_payload("invited@example.com", n=3)
    mine["invite_token"] = token
    assert (await client.post("/auth/register", json=mine)).status_code == 201
    again = await registration_payload("invited@example.com", n=4)
    again["invite_token"] = token
    assert (await client.post("/auth/register", json=again)).status_code in (400, 409)

    forged = await registration_payload("forged@example.com", n=5)
    forged["invite_token"] = "not-a-real-token"
    assert (await client.post("/auth/register", json=forged)).status_code == 400


async def test_pending_invitations_can_be_listed_and_revoked(
    authed_client: AsyncClient, client: AsyncClient, outbox: Outbox
) -> None:
    token = await _invite(authed_client, "pending@example.com", outbox)

    listed = (await authed_client.get("/auth/invitations")).json()
    assert [i["email"] for i in listed] == ["pending@example.com"]
    assert "token" not in listed[0] and "token_hash" not in listed[0]

    revoked = await authed_client.delete(f"/auth/invitations/{listed[0]['id']}")
    assert revoked.status_code == 204
    assert (await authed_client.delete(f"/auth/invitations/{listed[0]['id']}")).status_code == 404
    assert (await authed_client.get("/auth/invitations")).json() == []

    payload = await registration_payload("pending@example.com", n=6)
    payload["invite_token"] = token
    assert (await client.post("/auth/register", json=payload)).status_code == 400


async def test_only_admins_can_invite(client: AsyncClient) -> None:
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        response = await plain.post("/auth/invitations", json={"email": "x@example.com"})
        assert response.status_code == 403
        assert (await plain.get("/auth/invitations")).status_code == 403
    assert (
        await client.post("/auth/invitations", json={"email": "x@example.com"})
    ).status_code == 401


async def test_inviting_an_existing_account_conflicts(
    authed_client: AsyncClient,
) -> None:
    response = await authed_client.post(
        "/auth/invitations", json={"email": "all-roles@example.com"}
    )
    assert response.status_code == 409


async def test_invitations_only_grant_defined_roles(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/auth/invitations", json={"email": "r@example.com", "roles": ["superuser"]}
    )
    assert response.status_code == 422
