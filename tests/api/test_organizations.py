"""Phase A — Organizations core.

Every behaviour we require from the organizations layer gets a test here. Written first,
on purpose, so the service and migration below answer every one of them.
"""

import uuid

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.enums import PlatformRole
from tests.api.conftest import ClientFor, MakeUser, bearer_for


# -- the "my orgs" list ------------------------------------------------------------------


async def test_signed_in_user_has_a_personal_org(client: AsyncClient) -> None:
    """Every account that signs up gets a personal Organization with themselves as owner.

    This is the Phase A invariant that keeps the code single-pathed: there is no
    'individual' account, only an Organization with kind='personal' and one member.
    """
    r = await client.get("/orgs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    org = body["items"][0]
    assert org["kind"] == "personal"
    assert org["my_role"] == "owner"
    assert org["name"]
    assert org["slug"]


async def test_a_project_belongs_to_the_personal_org(client: AsyncClient) -> None:
    """When a logged-in user creates a project the project is created inside their
    personal org, so an org-scoped admin console can enumerate it."""
    created = await client.post("/projects", json={"name": "Blog"})
    assert created.status_code == 201
    project_id = created.json()["id"]

    orgs = (await client.get("/orgs")).json()["items"]
    slug = orgs[0]["slug"]

    r = await client.get(f"/orgs/{slug}/projects")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == project_id


# -- creating a team org ----------------------------------------------------------------


async def test_user_can_create_a_team_org_and_becomes_its_owner(client: AsyncClient) -> None:
    r = await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Acme"
    assert body["slug"] == "acme"
    assert body["kind"] == "team"
    assert body["my_role"] == "owner"
    assert body["member_count"] == 1

    # Now 'My orgs' lists both personal and team.
    orgs = (await client.get("/orgs")).json()
    assert orgs["total"] == 2


async def test_slug_must_be_unique(client: AsyncClient) -> None:
    assert (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).status_code == 201
    r = await client.post("/orgs", json={"name": "Second", "slug": "acme"})
    assert r.status_code == 409


async def test_cannot_see_someone_elses_org(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    other = await client_for("second@example.com")
    r = await other.get("/orgs/acme")
    assert r.status_code == 404  # same answer as 'does not exist'


# -- invitations ------------------------------------------------------------------------


async def test_admin_invites_and_invitee_accepts(
    client: AsyncClient, client_for: ClientFor
) -> None:
    create = await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert create.status_code == 201

    invite = await client.post(
        "/orgs/acme/invitations",
        json={"email": "bob@example.com", "role": "member"},
    )
    assert invite.status_code == 201
    body = invite.json()
    assert body["email"] == "bob@example.com"
    assert body["role"] == "member"
    assert body["status"] == "pending"
    assert body["token"]  # shown exactly once
    token = body["token"]

    # bob@example.com signs in, finds the pending invite and accepts.
    bob = await client_for("bob@example.com")
    pending = await bob.get("/orgs/invitations/pending")
    assert pending.status_code == 200
    pending_body = pending.json()
    assert len(pending_body["items"]) >= 1

    accept = await bob.post(f"/orgs/invitations/accept", json={"token": token})
    assert accept.status_code == 200
    joined = accept.json()
    assert joined["slug"] == "acme"
    assert joined["my_role"] == "member"

    # The owner now sees two members.
    members = (await client.get("/orgs/acme/members")).json()
    assert members["total"] == 2


async def test_invitation_cannot_exceed_plan_seat_cap(
    client: AsyncClient, session_factory
) -> None:
    """Pin seat_override=1 and the one owner already fills it, so the invite must 402.

    This is the §6.2 enforcement in the plan: platform is authoritative on usage, Stripe
    is authoritative on money. The counter includes pending invites.
    """
    r = await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201

    # Force the subscription to a 1-seat cap, same as a 'free'-plan team would be.
    from app.models.platform import Organization, Subscription
    from sqlalchemy import select

    async with session_factory() as session:
        org = (
            await session.execute(select(Organization).where(Organization.slug == "acme"))
        ).scalar_one()
        sub = await session.get(Subscription, org.id)
        assert sub is not None
        sub.seat_override = 1
        await session.commit()

    invite = await client.post(
        "/orgs/acme/invitations",
        json={"email": "bob@example.com", "role": "member"},
    )
    assert invite.status_code == 402
    assert invite.json()["code"] == "seat_limit"


async def test_members_endpoint_requires_org_membership(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    other = await client_for("stranger@example.com")
    r = await other.get("/orgs/acme/members")
    assert r.status_code == 404  # no leak that the org exists


async def test_only_admins_may_invite(
    client: AsyncClient, client_for: ClientFor, session_factory
) -> None:
    """A plain org_member cannot send invites (and seeing 'members' is enough visibility)."""
    await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    from app.models.enums import OrgRole
    from app.models.platform import (
        Organization,
        OrganizationMember,
        PlatformUser,
    )
    from app.services.platform_auth_service import normalize_email
    from sqlalchemy import select

    other = await client_for("member@example.com")

    async with session_factory() as session:
        row = (
            await session.execute(select(Organization).where(Organization.slug == "acme"))
        ).scalar_one()
        other_user = (
            await session.execute(
                select(PlatformUser).where(
                    PlatformUser.email == normalize_email("member@example.com")
                )
            )
        ).scalar_one()
        session.add(
            OrganizationMember(
                organization_id=row.id, user_id=other_user.id, role=OrgRole.member
            )
        )
        await session.commit()

    # Now the plain member tries to invite — must be 403.
    r = await other.post(
        "/orgs/acme/invitations",
        json={"email": "another@example.com", "role": "member"},
    )
    assert r.status_code == 403


async def test_owner_cannot_be_removed_if_last(
    client: AsyncClient, client_for: ClientFor
) -> None:
    """A team org always keeps at least one owner — same invariant as a project."""
    await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    owner_id = client.user.id  # type: ignore[attr-defined]
    r = await client.delete(f"/orgs/acme/members/{owner_id}")
    assert r.status_code == 409
    assert r.json()["code"] == "last_owner"
