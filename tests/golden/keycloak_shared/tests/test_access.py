"""Access-control tests for the entity routes (generated). Roles and row rules come from the
permissions in the spec; each test names the rule it checks."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import session_factory
from app.models.tickets import Ticket
from tests import _factories
from tests._auth_support import (
    ALL_ROLES,
    client_for,
    sign_in,
    sign_in_plain,
)

# The `outbox` fixture (tests/_auth_support.py) sets the test secrets and captures mail / SMS.
pytestmark = pytest.mark.usefixtures("outbox")


def _call(client: AsyncClient, op: str, path: str):  # type: ignore[no-untyped-def]
    """One request per operation. Ids are random and bodies empty: access is decided before
    either is looked at, so a refusal is the only possible answer."""
    missing = uuid.uuid4()
    match op:
        case "list":
            return client.get(f"/{path}")
        case "get":
            return client.get(f"/{path}/{missing}")
        case "head":
            return client.head(f"/{path}/{missing}")
        case "create":
            return client.post(f"/{path}", json={})
        case "replace":
            return client.put(f"/{path}/{missing}", json={})
        case "update":
            return client.patch(f"/{path}/{missing}", json={})
        case _:
            return client.delete(f"/{path}/{missing}")


async def test_tickets_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "list"):
        response = await _call(client, op, "tickets")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_tickets_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("delete",):
            response = await _call(plain, op, "tickets")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_tickets_rows_belong_to_their_creator(
    authed_client: AsyncClient, client: AsyncClient
) -> None:
    created = await _factories.make_tickets(authed_client)
    item_id = created["id"]
    me = (await authed_client.get("/auth/me")).json()
    async with session_factory() as session:
        stamped = (
            await session.execute(
                select(Ticket.created_by_id).where(Ticket.id == uuid.UUID(item_id))
            )
        ).scalar_one()
    assert str(stamped) == me["id"]

    # A second user who also holds every role: owner rules hide the row from them,
    # role_scoped rules let them see it because they hold the admin role.
    async with client_for(
        await sign_in(
            client,
            "second@example.com",
            roles=list(ALL_ROLES),
            n=1,
            join="all-roles@example.com",
        )
    ) as other:
        listing = await other.get("/tickets")
        assert listing.status_code == 200, listing.text
        assert listing.json()["total"] == 0
