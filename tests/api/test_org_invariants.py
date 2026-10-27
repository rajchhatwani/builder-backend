"""Backend gaps A–C, section 1: org invariants from PLATFORM_SAAS_PLAN §2.2, §3.2, §5.

- Only an owner can create or remove owners (admins: "change role (except Owner)").
- A user must belong to a project's org before joining the project; leaving the org removes
  their access to its projects.
- Deleting an org can't keep billing alive (the request flow is in test_org_deletion.py).
- Project writes stamp `organization_id` on their audit row.
- Org routes are authorized from one flat table (§5), default-deny.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.platform import AuditLog, Subscription
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]


async def _org_with(owner: AsyncClient, client_for: ClientFor, *people: tuple[str, str]) -> dict:
    """Create team org 'acme' owned by `owner`, then add each (email, role) via invite+accept."""
    r = await owner.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201
    clients = {}
    for email, role in people:
        inv = await owner.post("/orgs/acme/invitations", json={"email": email, "role": role})
        assert inv.status_code == 201, inv.text
        c = await client_for(email)
        accepted = await c.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
        assert accepted.status_code == 200, accepted.text
        clients[email] = c
    return clients


async def _member_id(owner: AsyncClient, email: str) -> str:
    members = (await owner.get("/orgs/acme/members")).json()["items"]
    return next(m["user_id"] for m in members if m["email"] == email)


# -- owners are made and unmade only by owners -------------------------------------------


async def test_admin_cannot_promote_to_owner(client: AsyncClient, client_for: ClientFor) -> None:
    people = await _org_with(
        client, client_for, ("admin@example.com", "admin"), ("bob@example.com", "member")
    )
    admin = people["admin@example.com"]
    bob = await _member_id(client, "bob@example.com")
    r = await admin.patch(f"/orgs/acme/members/{bob}", json={"role": "owner"})
    assert r.status_code == 403
    assert r.json()["code"] == "org_role_required"


async def test_admin_cannot_demote_or_remove_an_owner(
    client: AsyncClient, client_for: ClientFor
) -> None:
    people = await _org_with(
        client, client_for, ("admin@example.com", "admin"), ("co@example.com", "member")
    )
    co = await _member_id(client, "co@example.com")
    # The owner makes a second owner, so the "last owner" rule is not what stops the admin.
    assert (
        await client.patch(f"/orgs/acme/members/{co}", json={"role": "owner"})
    ).status_code == 200
    admin = people["admin@example.com"]
    assert (
        await admin.patch(f"/orgs/acme/members/{co}", json={"role": "member"})
    ).status_code == 403
    assert (await admin.delete(f"/orgs/acme/members/{co}")).status_code == 403


async def test_admin_cannot_invite_an_owner(client: AsyncClient, client_for: ClientFor) -> None:
    people = await _org_with(client, client_for, ("admin@example.com", "admin"))
    admin = people["admin@example.com"]
    r = await admin.post("/orgs/acme/invitations", json={"email": "x@example.com", "role": "owner"})
    assert r.status_code == 403
    # ...but the owner can.
    r = await client.post(
        "/orgs/acme/invitations", json={"email": "x@example.com", "role": "owner"}
    )
    assert r.status_code == 201


async def test_forbidden_names_the_owners(client: AsyncClient, client_for: ClientFor) -> None:
    """§8: a 403 on an admin-only panel tells the member whom to ask."""
    people = await _org_with(client, client_for, ("bob@example.com", "member"))
    r = await people["bob@example.com"].get("/orgs/acme/invitations")
    assert r.status_code == 403
    detail = r.json()["details"][0]
    assert detail["needed_role"] == "admin"
    assert detail["owner_emails"] == ["primary@example.com"]


# -- project membership follows org membership -------------------------------------------


async def _project_in_acme(owner: AsyncClient) -> str:
    acme = next(o for o in (await owner.get("/orgs")).json()["items"] if o["slug"] == "acme")
    r = await owner.post("/projects", json={"name": "App", "organization_id": acme["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["organization_id"] == acme["id"]
    return r.json()["id"]


async def test_project_member_must_belong_to_the_org(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await _org_with(client, client_for, ("bob@example.com", "member"))
    await client_for("outsider@example.com")
    pid = await _project_in_acme(client)

    r = await client.post(
        f"/projects/{pid}/members", json={"email": "outsider@example.com", "role": "viewer"}
    )
    assert r.status_code == 409
    assert r.json()["code"] == "not_an_org_member"

    r = await client.post(
        f"/projects/{pid}/members", json={"email": "bob@example.com", "role": "viewer"}
    )
    assert r.status_code == 201


async def test_leaving_the_org_drops_its_project_access(
    client: AsyncClient, client_for: ClientFor
) -> None:
    people = await _org_with(client, client_for, ("bob@example.com", "member"))
    bob = people["bob@example.com"]
    pid = await _project_in_acme(client)
    await client.post(
        f"/projects/{pid}/members", json={"email": "bob@example.com", "role": "editor"}
    )
    assert (await bob.get(f"/projects/{pid}")).status_code == 200

    bob_id = await _member_id(client, "bob@example.com")
    assert (await client.delete(f"/orgs/acme/members/{bob_id}")).status_code == 204
    assert (await bob.get(f"/projects/{pid}")).status_code == 404


async def test_cannot_create_a_project_in_someone_elses_org(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    acme_id = (await client.get("/orgs/acme")).json()["id"]
    other = await client_for("other@example.com")
    r = await other.post("/projects", json={"name": "Sneaky", "organization_id": acme_id})
    assert r.status_code == 403


# -- deleting an org ------------------------------------------------------------------------


async def test_cannot_delete_an_org_with_live_billing(
    client: AsyncClient, session_factory: Factory
) -> None:
    created = await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    org_id = uuid.UUID(created.json()["id"])
    async with session_factory() as session:
        sub = await session.get(Subscription, org_id)
        assert sub is not None
        sub.stripe_customer_id = "cus_1"
        sub.stripe_subscription_id = "sub_1"
        await session.commit()
    r = await client.delete("/orgs/acme")
    assert r.status_code == 409
    assert r.json()["code"] == "org_has_billing"


# -- audit stamping -----------------------------------------------------------------------


async def test_project_writes_are_stamped_with_the_org(
    client: AsyncClient, session_factory: Factory
) -> None:
    await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    pid = await _project_in_acme(client)
    acme_id = (await client.get("/orgs/acme")).json()["id"]
    version = (await client.get(f"/projects/{pid}")).json()["version"]
    r = await client.patch(f"/projects/{pid}", json={"description": "x", "version": version})
    assert r.status_code == 200, r.text
    async with session_factory() as session:
        row = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "project.change",
                    AuditLog.project_id == uuid.UUID(pid),
                )
            )
        ).scalar_one()
        assert str(row.organization_id) == acme_id


# -- §5: org routes come from one flat table, default-deny --------------------------------


def test_every_org_route_has_a_required_org_role() -> None:
    from app.api import security
    from app.core import platform_authz as authz
    from tests.api._routes import all_routes

    org_routes = [r for r in all_routes() if r.path.startswith("/orgs/{slug}")]
    assert len(org_routes) > 30  # the walker must really see the org routes (review F-001)
    missing = [
        (r.method, r.path)
        for r in org_routes
        if authz.required_org_role(r.method, r.path) is None
    ]
    assert missing == []
    # ... and every one of them goes through org_context
    assert [(r.method, r.path) for r in org_routes if security.org_context not in r.calls] == []


def test_unknown_org_route_is_denied() -> None:
    from app.core import platform_authz as authz

    assert authz.required_org_role("POST", "/orgs/{slug}/something-new") is None
