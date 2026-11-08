"""Backend gaps A–C, section 2: the customer org console API (PLATFORM_SAAS_PLAN §8)."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.platform import OrganizationInvitation
from app.services import mail_service
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]


async def _acme(owner: AsyncClient) -> str:
    r = await owner.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201
    return r.json()["id"]


async def _join(owner: AsyncClient, member: AsyncClient, role: str = "member") -> None:
    email = member.user.email  # type: ignore[attr-defined]
    inv = await owner.post("/orgs/acme/invitations", json={"email": email, "role": role})
    assert inv.status_code == 201, inv.text
    r = await member.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    assert r.status_code == 200, r.text


# -- invitations ---------------------------------------------------------------------------


async def test_accept_a_pending_invite_without_the_link(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await _acme(client)
    bob = await client_for("bob@example.com")
    await client.post("/orgs/acme/invitations", json={"email": "bob@example.com", "role": "admin"})
    pending = (await bob.get("/orgs/invitations/pending")).json()["items"]
    assert len(pending) == 1
    r = await bob.post(f"/orgs/invitations/{pending[0]['id']}/accept")
    assert r.status_code == 200, r.text
    assert r.json()["my_role"] == "admin"


async def test_accept_by_id_only_for_the_invited_address(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await _acme(client)
    inv = await client.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    mallory = await client_for("mallory@example.com")
    r = await mallory.post(f"/orgs/invitations/{inv.json()['id']}/accept")
    assert r.status_code == 404


async def test_resend_rotates_the_link(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    await _acme(client)
    first = (
        await client.post(
            "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
        )
    ).json()
    r = await client.post(f"/orgs/acme/invitations/{first['id']}/resend")
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["token"] != first["token"]
    assert second["invite_url"].endswith(f"/#/invite/{second['token']}")

    bob = await client_for("bob@example.com")
    old = await bob.post("/orgs/invitations/accept", json={"token": first["token"]})
    assert old.status_code == 404  # the old link is dead
    new = await bob.post("/orgs/invitations/accept", json={"token": second["token"]})
    assert new.status_code == 200


async def test_resend_revives_an_expired_invite(
    client: AsyncClient, session_factory: Factory
) -> None:
    from datetime import UTC, datetime, timedelta

    await _acme(client)
    inv = (
        await client.post(
            "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
        )
    ).json()
    async with session_factory() as session:
        row = await session.get(OrganizationInvitation, uuid.UUID(inv["id"]))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
        await session.commit()
    r = await client.post(f"/orgs/acme/invitations/{inv['id']}/resend")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


async def test_invites_are_emailed_when_smtp_is_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []

    async def fake_send(to: str, subject: str, body: str) -> bool:
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(mail_service, "send", fake_send)
    await _acme(client)
    r = await client.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    body = r.json()
    assert body["emailed"] is True
    assert sent[0]["to"] == "bob@example.com"
    assert body["invite_url"] in sent[0]["body"]


async def test_without_smtp_the_invite_is_not_emailed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BUILDER_SMTP_HOST", raising=False)
    get_settings.cache_clear()
    await _acme(client)
    r = await client.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    assert r.json()["emailed"] is False
    assert r.json()["invite_url"].startswith(get_settings().public_app_url)


# -- org settings --------------------------------------------------------------------------


async def test_admin_can_rename_the_org(client: AsyncClient, client_for: ClientFor) -> None:
    await _acme(client)
    r = await client.patch("/orgs/acme", json={"name": "Acme Inc"})
    assert r.status_code == 200
    assert (await client.get("/orgs/acme")).json()["name"] == "Acme Inc"
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    assert (await bob.patch("/orgs/acme", json={"name": "Nope"})).status_code == 403


async def test_people_table_has_status_and_last_sign_in(client: AsyncClient) -> None:
    await _acme(client)
    member = (await client.get("/orgs/acme/members")).json()["items"][0]
    assert member["status"] == "active"
    assert "last_login_at" in member


async def test_default_org_can_be_chosen(client: AsyncClient, client_for: ClientFor) -> None:
    acme = await _acme(client)
    me = (await client.get("/account/me")).json()
    assert me["default_organization_id"]  # the personal org
    r = await client.put("/account/me/default-organization", json={"organization_id": acme})
    assert r.status_code == 200
    assert r.json()["default_organization_id"] == acme
    # New projects land there by default now.
    created = await client.post("/projects", json={"name": "InAcme"})
    assert created.json()["organization_id"] == acme
    # Not a member → 404.
    other = await client_for("other@example.com")
    r = await other.put("/account/me/default-organization", json={"organization_id": acme})
    assert r.status_code == 404


# -- projects tab ----------------------------------------------------------------------------


async def test_members_only_see_their_own_org_projects(
    client: AsyncClient, client_for: ClientFor
) -> None:
    acme = await _acme(client)
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    mine = (await client.post("/projects", json={"name": "Shared", "organization_id": acme})).json()
    await client.post("/projects", json={"name": "Private", "organization_id": acme})
    await client.post(
        f"/projects/{mine['id']}/members", json={"email": "bob@example.com", "role": "viewer"}
    )
    assert (await client.get("/orgs/acme/projects")).json()["total"] == 2  # owner sees all
    names = [p["name"] for p in (await bob.get("/orgs/acme/projects")).json()["items"]]
    assert names == ["Shared"]


async def test_org_admin_can_join_an_org_project(
    client: AsyncClient, client_for: ClientFor
) -> None:
    acme = await _acme(client)
    admin = await client_for("admin@example.com")
    await _join(client, admin, "admin")
    pid = (await client.post("/projects", json={"name": "App", "organization_id": acme})).json()[
        "id"
    ]
    assert (await admin.get(f"/projects/{pid}")).status_code == 404
    r = await admin.post(f"/orgs/acme/projects/{pid}/join", json={"role": "editor"})
    assert r.status_code == 201
    assert (await admin.get(f"/projects/{pid}")).status_code == 200
    # Members can't.
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    assert (await bob.post(f"/orgs/acme/projects/{pid}/join", json={})).status_code == 403


async def test_owner_moves_a_project_between_their_orgs(client: AsyncClient) -> None:
    acme = await _acme(client)
    beta = (await client.post("/orgs", json={"name": "Beta", "slug": "beta"})).json()["id"]
    pid = (await client.post("/projects", json={"name": "App", "organization_id": acme})).json()[
        "id"
    ]
    r = await client.post(f"/orgs/acme/projects/{pid}/transfer", json={"to_slug": "beta"})
    assert r.status_code == 200, r.text
    assert r.json()["organization_id"] == beta
    assert (await client.get("/orgs/acme/projects")).json()["total"] == 0
    assert (await client.get("/orgs/beta/projects")).json()["total"] == 1


async def test_transfer_needs_every_project_member_in_the_destination(
    client: AsyncClient, client_for: ClientFor
) -> None:
    acme = await _acme(client)
    await client.post("/orgs", json={"name": "Beta", "slug": "beta"})
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    pid = (await client.post("/projects", json={"name": "App", "organization_id": acme})).json()[
        "id"
    ]
    await client.post(
        f"/projects/{pid}/members", json={"email": "bob@example.com", "role": "viewer"}
    )
    r = await client.post(f"/orgs/acme/projects/{pid}/transfer", json={"to_slug": "beta"})
    assert r.status_code == 409
    assert r.json()["code"] == "not_an_org_member"


async def test_transfer_needs_ownership_of_the_destination(
    client: AsyncClient, client_for: ClientFor
) -> None:
    acme = await _acme(client)
    other = await client_for("other@example.com")
    assert (await other.post("/orgs", json={"name": "Beta", "slug": "beta"})).status_code == 201
    pid = (await client.post("/projects", json={"name": "App", "organization_id": acme})).json()[
        "id"
    ]
    r = await client.post(f"/orgs/acme/projects/{pid}/transfer", json={"to_slug": "beta"})
    assert r.status_code == 404  # not even a member of beta


async def test_transfer_respects_the_destination_project_cap(
    client: AsyncClient, session_factory: Factory
) -> None:
    from app.models.platform import Subscription

    acme = await _acme(client)
    beta = (await client.post("/orgs", json={"name": "Beta", "slug": "beta"})).json()["id"]
    async with session_factory() as session:
        sub = await session.get(Subscription, uuid.UUID(beta))
        assert sub is not None
        sub.project_override = 0
        await session.commit()
    pid = (await client.post("/projects", json={"name": "App", "organization_id": acme})).json()[
        "id"
    ]
    r = await client.post(f"/orgs/acme/projects/{pid}/transfer", json={"to_slug": "beta"})
    assert r.status_code == 402


# -- org audit -----------------------------------------------------------------------------


async def test_org_audit_is_scoped_and_hides_details(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await _acme(client)
    await client.post("/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"})
    other = await client_for("other@example.com")
    await other.post("/orgs", json={"name": "Other", "slug": "other"})

    r = await client.get("/orgs/acme/audit")
    assert r.status_code == 200
    items = r.json()["items"]
    actions = {i["action"] for i in items}
    assert {"org.created", "org.invitation_created"} <= actions
    assert all("detail" not in i and "client_ip" not in i for i in items)
    # The other org's events never show up here.
    assert all(i["actor_email"] != "other@example.com" for i in items)


async def test_members_cannot_read_the_org_audit(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await _acme(client)
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    assert (await bob.get("/orgs/acme/audit")).status_code == 403


async def test_api_token_scopes_apply_to_org_routes(client: AsyncClient) -> None:
    """A read-only API token must not be able to invite people."""
    from httpx import ASGITransport

    from app.main import app

    await _acme(client)
    token = (await client.post("/account/tokens", json={"name": "ro", "scopes": ["read"]})).json()[
        "token"
    ]
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as ro:
        assert (await ro.get("/orgs/acme")).status_code == 200
        r = await ro.post(
            "/orgs/acme/invitations", json={"email": "x@example.com", "role": "member"}
        )
        assert r.status_code == 403


# -- review F-010: People columns for last sign-in and 2FA are for admins ------------------------


async def test_plain_members_do_not_see_other_peoples_login_and_2fa(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await client.post("/orgs", json={"name": "Vis", "slug": "vis-co"})
    member = await client_for("vis-member@example.com")
    invite = await client.post(
        "/orgs/vis-co/invitations", json={"email": "vis-member@example.com", "role": "member"}
    )
    await member.post("/orgs/invitations/accept", json={"token": invite.json()["token"]})

    seen = {m["email"]: m for m in (await member.get("/orgs/vis-co/members")).json()["items"]}
    assert "last_login_at" not in seen["primary@example.com"]
    assert "mfa_enabled" not in seen["primary@example.com"]
    assert "mfa_enabled" in seen["vis-member@example.com"]  # their own row is theirs to see

    seen_by_owner = {m["email"]: m for m in (await client.get("/orgs/vis-co/members")).json()["items"]}
    assert seen_by_owner["vis-member@example.com"]["mfa_enabled"] is False
    assert "last_login_at" in seen_by_owner["vis-member@example.com"]
