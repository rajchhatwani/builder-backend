"""Phase E — SCIM 2.0 directory sync (PLATFORM_SAAS_PLAN §4.3, §12.E).

Setup by org admins (gated on `plans.allow_scim`), the protocol endpoints the IdP calls with the
org's bearer token, offboarding (`active: false` / DELETE), group -> role mapping, tenant isolation
and the operator's token rotation.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_security as sec
from app.models.enums import MemberRole, OrgRole, PlatformRole
from app.models.platform import (
    ApiToken,
    AuditLog,
    Organization,
    OrganizationMember,
    PlatformUser,
    ProjectMember,
    RefreshToken,
)
from app.models.scim import ScimDirectory
from app.services import dns_txt
from app.services import scim_protocol as proto
from tests.api.conftest import ClientFor
from tests.api.test_sso_config import set_plan, verified_domain

Factory = async_sessionmaker[AsyncSession]
SCIM = "/scim/v2"
pytestmark = pytest.mark.usefixtures("dns")


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """DNS TXT answers for domain verification (same fake as test_sso_config)."""
    records: dict[str, list[str]] = {}

    async def fake(name: str) -> list[str]:
        return records.get(name, [])

    monkeypatch.setattr(dns_txt, "txt_records", fake)
    return records


async def enterprise_org(
    client: AsyncClient,
    factory: Factory,
    dns: dict[str, list[str]],
    slug: str = "acme",
    domain: str = "acme.test",
) -> str:
    org = (await client.post("/orgs", json={"name": slug.title(), "slug": slug})).json()["id"]
    await set_plan(factory, org, "enterprise")
    await verified_domain(client, dns, domain, slug)
    return org


async def scim_token(client: AsyncClient, slug: str = "acme") -> dict[str, str]:
    r = await client.post(f"/orgs/{slug}/scim/token")
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def user_body(email: str = "alice@acme.test", **extra: object) -> dict[str, object]:
    return {
        "schemas": [proto.USER_SCHEMA],
        "userName": email,
        "name": {"givenName": "Alice", "familyName": "Smith"},
        "emails": [{"primary": True, "value": email, "type": "work"}],
        "externalId": "ext-" + email,
        "active": True,
        **extra,
    }


def ops(*items: dict[str, object]) -> dict[str, object]:
    return {"schemas": [proto.PATCH_OP_SCHEMA], "Operations": list(items)}


async def provision(anon: AsyncClient, h: dict[str, str], email: str = "alice@acme.test") -> dict:
    r = await anon.post(f"{SCIM}/Users", json=user_body(email), headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def member_role(factory: Factory, org_id: str, email: str) -> OrgRole | None:
    async with factory() as s:
        user = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == email))
        ).scalar_one()
        m = await s.get(OrganizationMember, (uuid.UUID(org_id), user.id))
        return m.role if m else None


async def actions(factory: Factory, prefix: str) -> list[AuditLog]:
    async with factory() as s:
        return list(
            (
                await s.execute(
                    select(AuditLog).where(AuditLog.action.like(prefix + "%")).order_by(AuditLog.id)
                )
            ).scalars()
        )


# == setup ======================================================================================


async def test_unconfigured_status_shows_the_base_url(
    client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    r = await client.get("/orgs/acme/scim")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is False
    assert body["allowed_by_plan"] is False  # 'team' has no SCIM
    assert body["base_url"].endswith("/scim/v2")
    assert body["users_url"].endswith("/scim/v2/Users")


async def test_scim_needs_a_plan_that_allows_it(
    client: AsyncClient, session_factory: Factory
) -> None:
    await client.post("/orgs", json={"name": "Acme", "slug": "acme"})
    r = await client.post("/orgs/acme/scim/token")
    assert r.status_code == 402
    assert r.json()["code"] == "scim_not_in_plan"
    assert r.json()["details"][0]["resource"] == "scim"
    denied = await actions(session_factory, "quota.denied")
    assert denied and denied[-1].detail["resource"] == "scim"  # type: ignore[index]


async def test_personal_orgs_have_no_scim(client: AsyncClient) -> None:
    slug = (await client.get("/orgs")).json()["items"][0]["slug"]
    r = await client.post(f"/orgs/{slug}/scim/token")
    assert r.status_code == 409
    assert r.json()["code"] == "scim_not_for_personal_orgs"


async def test_token_is_shown_once_and_only_its_hash_is_kept(
    client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    r = await client.post("/orgs/acme/scim/token")
    assert r.status_code == 201, r.text
    body = r.json()
    token = body["token"]
    assert token.startswith("bb_scim_")
    assert body["configured"] is True and body["active"] is True
    assert body["token_hint"] == token[-4:]
    status = (await client.get("/orgs/acme/scim")).json()
    assert "token" not in status and status["token_hint"] == token[-4:]
    async with session_factory() as s:
        row = await s.get(ScimDirectory, uuid.UUID(org))
        assert row is not None and row.bearer_hash == sec.hash_token(token)
        logs = list((await s.execute(select(AuditLog))).scalars())
    assert any(log.action == "scim.directory_created" for log in logs)
    assert all(token not in str(log.detail) for log in logs)


async def test_rotation_kills_the_old_token(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    old = await scim_token(client)
    r = await client.post("/orgs/acme/scim/token")
    assert r.status_code == 200
    new = {"Authorization": f"Bearer {r.json()['token']}"}
    assert (await anon_client.get(f"{SCIM}/Users", headers=old)).status_code == 401
    assert (await anon_client.get(f"{SCIM}/Users", headers=new)).status_code == 200
    assert await actions(session_factory, "scim.token_rotated")
    # An admin who switched SCIM off keeps it off when rotating; only an operator rotation's
    # switch-off is undone by a fresh token.
    assert (await client.patch("/orgs/acme/scim", json={"active": False})).status_code == 200
    r = await client.post("/orgs/acme/scim/token")
    assert r.status_code == 200 and r.json()["active"] is False
    off = {"Authorization": f"Bearer {r.json()['token']}"}
    assert (await anon_client.get(f"{SCIM}/Users", headers=off)).status_code == 401


async def test_switching_off_and_removing_the_directory(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    await provision(anon_client, h)
    r = await client.patch("/orgs/acme/scim", json={"active": False})
    assert r.status_code == 200 and r.json()["active"] is False
    assert (await anon_client.get(f"{SCIM}/Users", headers=h)).status_code == 401
    assert (await client.patch("/orgs/acme/scim", json={"active": True})).json()["active"]
    assert (await client.delete("/orgs/acme/scim")).status_code == 204
    assert (await anon_client.get(f"{SCIM}/Users", headers=h)).status_code == 401
    assert (await client.get("/orgs/acme/scim")).json()["configured"] is False
    # Removing the directory keeps the people it provisioned.
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.member


async def test_setup_is_for_admins_with_a_session(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    bob = await client_for("bob@example.com")
    async with session_factory() as s:
        s.add(
            OrganizationMember(
                organization_id=uuid.UUID(org),
                user_id=bob.user.id,  # type: ignore[attr-defined]
                role=OrgRole.member,
            )
        )
        await s.commit()
    r = await bob.get("/orgs/acme/scim")
    assert r.status_code == 403 and r.json()["code"] == "org_role_required"
    pat = (
        await client.post("/account/tokens", json={"name": "ci", "scopes": ["read", "write"]})
    ).json()["token"]
    r = await client.post("/orgs/acme/scim/token", headers={"Authorization": f"Bearer {pat}"})
    assert r.status_code == 403 and r.json()["code"] == "session_required"


async def test_only_owners_may_map_a_group_to_owner(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    await scim_token(client)
    admin = await client_for("admin@example.com")
    async with session_factory() as s:
        s.add(
            OrganizationMember(
                organization_id=uuid.UUID(org),
                user_id=admin.user.id,  # type: ignore[attr-defined]
                role=OrgRole.admin,
            )
        )
        await s.commit()
    r = await admin.patch("/orgs/acme/scim", json={"group_roles": {"Owners": "owner"}})
    assert r.status_code == 403 and r.json()["code"] == "org_role_required"
    r = await admin.patch("/orgs/acme/scim", json={"group_roles": {"Admins": "admin"}})
    assert r.status_code == 200 and r.json()["group_roles"] == {"admins": "admin"}
    r = await client.patch("/orgs/acme/scim", json={"group_roles": {"Owners": "owner"}})
    assert r.status_code == 200
    # Once an owner mapping exists, an admin can't remove it either.
    r = await admin.patch("/orgs/acme/scim", json={"group_roles": {}})
    assert r.status_code == 403
    r = await client.patch("/orgs/acme/scim", json={"group_roles": {"x": "superuser"}})
    assert r.status_code == 422


# == protocol: auth + discovery =================================================================


async def test_no_or_wrong_token_is_a_scim_401(anon_client: AsyncClient) -> None:
    for headers in ({}, {"Authorization": "Bearer bb_scim_nope"}, {"Authorization": "Basic x"}):
        r = await anon_client.get(f"{SCIM}/Users", headers=headers)
        assert r.status_code == 401
        assert r.headers["content-type"].startswith("application/scim+json")
        assert r.json()["schemas"] == [proto.ERROR_SCHEMA]
        assert r.headers["www-authenticate"].startswith("Bearer")


async def test_discovery_endpoints(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    spc = (await anon_client.get(f"{SCIM}/ServiceProviderConfig", headers=h)).json()
    assert spc["patch"]["supported"] is True
    types = (await anon_client.get(f"{SCIM}/ResourceTypes", headers=h)).json()
    assert {t["id"] for t in types["Resources"]} == {"User", "Group"}
    assert (await anon_client.get(f"{SCIM}/ResourceTypes/User", headers=h)).status_code == 200
    schemas = (await anon_client.get(f"{SCIM}/Schemas", headers=h)).json()
    assert schemas["totalResults"] == 2
    r = await anon_client.get(f"{SCIM}/Schemas/{proto.USER_SCHEMA}", headers=h)
    assert r.status_code == 200 and r.json()["name"] == "User"
    assert (await anon_client.get(f"{SCIM}/Schemas/nope", headers=h)).status_code == 404


async def test_plan_downgrade_or_deletion_lock_stops_the_directory(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    await set_plan(session_factory, org, "business")
    r = await anon_client.get(f"{SCIM}/Users", headers=h)
    assert r.status_code == 403 and "plan" in r.json()["detail"]
    await set_plan(session_factory, org, "enterprise")
    async with session_factory() as s:
        o = await s.get(Organization, uuid.UUID(org))
        assert o is not None
        from datetime import UTC, datetime

        o.deletion_requested_at = datetime.now(UTC)
        await s.commit()
    assert (await anon_client.get(f"{SCIM}/Users", headers=h)).status_code == 403


async def test_requests_record_the_last_sync(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    assert (await client.get("/orgs/acme/scim")).json()["last_sync_at"] is None
    await anon_client.get(f"{SCIM}/Users", headers=h)
    assert (await client.get("/orgs/acme/scim")).json()["last_sync_at"] is not None


# == users ======================================================================================


async def test_create_user_provisions_an_sso_only_member(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.billing_service import BillingService

    synced: list[uuid.UUID] = []

    async def fake_sync(self: BillingService, organization_id: uuid.UUID, **_: object) -> None:
        synced.append(organization_id)

    monkeypatch.setattr(BillingService, "sync_seats", fake_sync)
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    r = await anon_client.post(f"{SCIM}/Users", json=user_body(), headers=h)
    assert r.status_code == 201, r.text
    assert r.headers["content-type"].startswith("application/scim+json")
    body = r.json()
    assert r.headers["location"] == body["meta"]["location"]
    assert body["userName"] == "alice@acme.test"
    assert body["active"] is True
    assert body["name"]["givenName"] == "Alice"
    assert body["emails"][0]["value"] == "alice@acme.test"
    assert synced == [uuid.UUID(org)]
    async with session_factory() as s:
        user = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one()
        assert user.password_hash == sec.SSO_ONLY_PASSWORD_HASH
        assert user.name == "Alice Smith"
        personal = (
            (
                await s.execute(
                    select(OrganizationMember).where(
                        OrganizationMember.user_id == user.id,
                        OrganizationMember.role == OrgRole.owner,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(personal) == 1  # their personal org
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.member
    created = await actions(session_factory, "scim.user_created")
    assert created and created[0].via == "scim" and str(created[0].organization_id) == org

    got = await anon_client.get(f"{SCIM}/Users/{body['id']}", headers=h)
    assert got.status_code == 200 and got.json()["id"] == body["id"]
    listed = await anon_client.get(
        f"{SCIM}/Users", params={"filter": 'userName eq "ALICE@acme.test"'}, headers=h
    )
    assert listed.json()["totalResults"] == 1
    assert listed.json()["Resources"][0]["id"] == body["id"]
    for f in ('externalId eq "ext-alice@acme.test"', 'emails.value eq "alice@acme.test"'):
        res = await anon_client.get(f"{SCIM}/Users", params={"filter": f}, headers=h)
        assert res.json()["totalResults"] == 1, f
    none = await anon_client.get(
        f"{SCIM}/Users", params={"filter": 'userName eq "nobody@acme.test"'}, headers=h
    )
    assert none.json() == proto.list_response([], total=0, start_index=1)
    bad = await anon_client.get(f"{SCIM}/Users", params={"filter": 'title co "x"'}, headers=h)
    assert bad.status_code == 400 and bad.json()["scimType"] == "invalidFilter"


async def test_duplicates_bad_domains_and_staff_are_refused(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
    make_user: object,
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    await provision(anon_client, h)
    dup = await anon_client.post(f"{SCIM}/Users", json=user_body(), headers=h)
    assert dup.status_code == 409 and dup.json()["scimType"] == "uniqueness"
    other = await anon_client.post(f"{SCIM}/Users", json=user_body("eve@evil.test"), headers=h)
    assert other.status_code == 400 and "verified domain" in other.json()["detail"]
    await make_user("ops@acme.test", PlatformRole.platform_admin)  # type: ignore[operator]
    staff = await anon_client.post(f"{SCIM}/Users", json=user_body("ops@acme.test"), headers=h)
    assert staff.status_code == 400
    malformed = await anon_client.post(
        f"{SCIM}/Users", content=b"{nope", headers={**h, "Content-Type": "application/scim+json"}
    )
    assert malformed.status_code == 400 and malformed.json()["scimType"] == "invalidSyntax"
    missing = await anon_client.get(f"{SCIM}/Users/{uuid.uuid4()}", headers=h)
    assert missing.status_code == 404
    assert (await anon_client.get(f"{SCIM}/Users/not-a-uuid", headers=h)).status_code == 404


async def test_existing_account_on_the_domain_is_linked(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
    make_user: object,
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    existing = await make_user("carol@acme.test")  # type: ignore[operator]
    h = await scim_token(client)
    await provision(anon_client, h, "carol@acme.test")
    async with session_factory() as s:
        users = (
            (await s.execute(select(PlatformUser).where(PlatformUser.email == "carol@acme.test")))
            .scalars()
            .all()
        )
        assert [u.id for u in users] == [existing.id]
        assert users[0].password_hash != sec.SSO_ONLY_PASSWORD_HASH  # their password stays
    assert await member_role(session_factory, org, "carol@acme.test") is OrgRole.member


async def test_seat_limit_applies_to_scim_create(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    from app.models.platform import Subscription

    async with session_factory() as s:
        sub = await s.get(Subscription, uuid.UUID(org))
        assert sub is not None
        sub.seat_override = 1  # the owner already fills it
        await s.commit()
    r = await anon_client.post(f"{SCIM}/Users", json=user_body(), headers=h)
    assert r.status_code == 403 and "seat" in r.json()["detail"]
    denied = await actions(session_factory, "quota.denied")
    assert denied[-1].detail["resource"] == "seats"  # type: ignore[index]
    # Nothing was half-created.
    listed = (await anon_client.get(f"{SCIM}/Users", headers=h)).json()
    assert listed["totalResults"] == 0
    # An inactive user takes no seat.
    r = await anon_client.post(f"{SCIM}/Users", json=user_body(active=False), headers=h)
    assert r.status_code == 201 and r.json()["active"] is False


async def test_put_and_patch_update_the_user(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    r = await anon_client.put(
        f"{SCIM}/Users/{uid}",
        json=user_body(name={"givenName": "Al", "familyName": "Smith"}, displayName="Al S"),
        headers=h,
    )
    assert r.status_code == 200 and r.json()["name"]["givenName"] == "Al"
    r = await anon_client.patch(
        f"{SCIM}/Users/{uid}",
        json=ops({"op": "Replace", "path": "name.familyName", "value": "Jones"}),
        headers=h,
    )
    assert r.status_code == 200 and r.json()["name"]["familyName"] == "Jones"
    # Renaming to an address on the verified domain changes the Builder account's e-mail.
    r = await anon_client.patch(
        f"{SCIM}/Users/{uid}",
        json=ops({"op": "replace", "path": "userName", "value": "al.jones@acme.test"}),
        headers=h,
    )
    assert r.status_code == 200 and r.json()["emails"][0]["value"] == "al.jones@acme.test"
    r = await anon_client.patch(
        f"{SCIM}/Users/{uid}",
        json=ops({"op": "replace", "path": "userName", "value": "al@elsewhere.test"}),
        headers=h,
    )
    assert r.status_code == 400
    r = await anon_client.patch(
        f"{SCIM}/Users/{uid}", json=ops({"op": "replace", "path": "id", "value": "x"}), headers=h
    )
    assert r.status_code == 400 and r.json()["scimType"] == "mutability"


async def _alice_with_access(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> tuple[str, dict[str, str], str, str]:
    """Alice is provisioned, owns a project in the org alone and holds sessions + tokens."""
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    created = await client.post("/projects", json={"name": "Shop", "organization_id": org})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    async with session_factory() as s:
        alice = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one()
        owner_row = await s.get(ProjectMember, (uuid.UUID(project_id), client.user.id))  # type: ignore[attr-defined]
        assert owner_row is not None
        await s.delete(owner_row)  # Alice becomes the project's only owner
        s.add(
            ProjectMember(project_id=uuid.UUID(project_id), user_id=alice.id, role=MemberRole.owner)
        )
        from datetime import UTC, datetime, timedelta

        s.add(
            ApiToken(
                user_id=alice.id,
                name="pinned",
                public_id="pinned0001",
                token_hash="x" * 64,
                scopes=["read"],
                project_id=uuid.UUID(project_id),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        s.add(
            ApiToken(
                user_id=alice.id,
                name="personal",
                public_id="personal01",
                token_hash="y" * 64,
                scopes=["read"],
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        s.add(
            RefreshToken(
                user_id=alice.id,
                family_id=uuid.uuid4(),
                audience="app",
                token_hash="z" * 64,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await s.commit()
    return org, h, uid, project_id


async def test_deactivation_offboards_from_this_org_only(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org, h, uid, project_id = await _alice_with_access(client, anon_client, session_factory, dns)
    async with session_factory() as s:
        before = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one()
        version = before.token_version
    # Okta's shape: a path-less replace.
    r = await anon_client.patch(
        f"{SCIM}/Users/{uid}", json=ops({"op": "replace", "value": {"active": False}}), headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False
    assert await member_role(session_factory, org, "alice@acme.test") is None
    async with session_factory() as s:
        alice = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one()
        assert alice.token_version == version + 1  # access tokens die
        refresh = (
            (await s.execute(select(RefreshToken).where(RefreshToken.user_id == alice.id)))
            .scalars()
            .all()
        )
        assert all(t.revoked_at is not None for t in refresh)
        tokens = {
            t.name: t
            for t in (
                await s.execute(select(ApiToken).where(ApiToken.user_id == alice.id))
            ).scalars()
        }
        assert tokens["pinned"].revoked_at is not None  # this org's tokens die
        assert tokens["personal"].revoked_at is None  # (it lost the org with the membership)
        members = (
            (
                await s.execute(
                    select(ProjectMember).where(ProjectMember.project_id == uuid.UUID(project_id))
                )
            )
            .scalars()
            .all()
        )
        # The project she owned alone went to an org owner, not into limbo.
        assert [(m.user_id, m.role) for m in members] == [(client.user.id, MemberRole.owner)]  # type: ignore[attr-defined]
        personal = (
            (
                await s.execute(
                    select(OrganizationMember).where(OrganizationMember.user_id == alice.id)
                )
            )
            .scalars()
            .all()
        )
        assert [m.role for m in personal] == [OrgRole.owner]  # her personal org stays
        assert alice.default_organization_id == personal[0].organization_id
    assert await actions(session_factory, "scim.user_deactivated")
    assert await actions(session_factory, "scim.project_handed_over")
    # Still readable by the IdP, and it can come back (Entra's shape: string boolean).
    got = await anon_client.get(f"{SCIM}/Users/{uid}", headers=h)
    assert got.json()["active"] is False
    r = await anon_client.patch(
        f"{SCIM}/Users/{uid}",
        json=ops({"op": "Replace", "path": "active", "value": "True"}),
        headers=h,
    )
    assert r.status_code == 200 and r.json()["active"] is True
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.member


async def test_deactivated_member_loses_api_access(
    client: AsyncClient,
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    async with session_factory() as s:
        alice = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one()
    from tests.api.conftest import bearer_for

    headers = bearer_for(alice)
    assert (await anon_client.get("/orgs/acme", headers=headers)).status_code == 200
    await anon_client.patch(
        f"{SCIM}/Users/{uid}",
        json=ops({"op": "replace", "path": "active", "value": False}),
        headers=h,
    )
    assert (await anon_client.get("/orgs/acme", headers=headers)).status_code == 401


async def test_the_last_owner_cannot_be_offboarded(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
    make_user: object,
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    async with session_factory() as s:
        for m in (
            await s.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == uuid.UUID(org)
                )
            )
        ).scalars():
            if m.role is OrgRole.owner:
                await s.delete(m)
        alice = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one()
        m = await s.get(OrganizationMember, (uuid.UUID(org), alice.id))
        assert m is not None
        m.role = OrgRole.owner
        await s.commit()
    r = await anon_client.patch(
        f"{SCIM}/Users/{uid}",
        json=ops({"op": "replace", "path": "active", "value": False}),
        headers=h,
    )
    assert r.status_code == 409 and r.json()["scimType"] == "mutability"
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.owner
    assert (await anon_client.get(f"{SCIM}/Users/{uid}", headers=h)).json()["active"] is True


async def test_delete_user_offboards_and_forgets_the_resource(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    assert (await anon_client.delete(f"{SCIM}/Users/{uid}", headers=h)).status_code == 204
    assert (await anon_client.get(f"{SCIM}/Users/{uid}", headers=h)).status_code == 404
    assert await member_role(session_factory, org, "alice@acme.test") is None
    async with session_factory() as s:  # the account itself stays
        assert (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one()
    assert await actions(session_factory, "scim.user_deleted")


async def test_paging(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    for i in range(3):
        await provision(anon_client, h, f"u{i}@acme.test")
    page = (
        await anon_client.get(f"{SCIM}/Users", params={"startIndex": 2, "count": 1}, headers=h)
    ).json()
    assert page["totalResults"] == 3 and page["startIndex"] == 2 and page["itemsPerPage"] == 1
    assert page["Resources"][0]["userName"] == "u1@acme.test"


# == tenant isolation ===========================================================================


async def test_one_orgs_token_never_reaches_another_org(
    client: AsyncClient,
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    ha = await scim_token(client)
    a_user = (await provision(anon_client, ha))["id"]
    a_group = (
        await anon_client.post(
            f"{SCIM}/Groups",
            json={"displayName": "Eng", "members": [{"value": a_user}]},
            headers=ha,
        )
    ).json()["id"]
    other = await client_for("boss@globex.test")
    await enterprise_org(other, session_factory, dns, "globex", "globex.test")
    hb = await scim_token(other, "globex")
    assert (await anon_client.get(f"{SCIM}/Users", headers=hb)).json()["totalResults"] == 0
    for method, path in (
        ("GET", f"/Users/{a_user}"),
        ("PATCH", f"/Users/{a_user}"),
        ("DELETE", f"/Users/{a_user}"),
        ("GET", f"/Groups/{a_group}"),
        ("DELETE", f"/Groups/{a_group}"),
    ):
        r = await anon_client.request(
            method,
            SCIM + path,
            headers=hb,
            json=ops({"op": "replace", "path": "active", "value": False}),
        )
        assert r.status_code == 404, f"{method} {path}"
    # B can't put A's user into its group, nor provision on A's domain.
    g = await anon_client.post(
        f"{SCIM}/Groups", json={"displayName": "Eng", "members": [{"value": a_user}]}, headers=hb
    )
    assert g.status_code == 201 and g.json()["members"] == []
    r = await anon_client.post(f"{SCIM}/Users", json=user_body("x@acme.test"), headers=hb)
    assert r.status_code == 400
    assert (await anon_client.get(f"{SCIM}/Users/{a_user}", headers=ha)).json()["active"] is True


# == groups and roles ===========================================================================


async def test_groups_crud_and_entra_style_patches(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    u1 = (await provision(anon_client, h, "u1@acme.test"))["id"]
    u2 = (await provision(anon_client, h, "u2@acme.test"))["id"]
    r = await anon_client.post(
        f"{SCIM}/Groups",
        json={
            "schemas": [proto.GROUP_SCHEMA],
            "displayName": "Engineering",
            "members": [{"value": u1}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    assert [m["value"] for m in r.json()["members"]] == [u1]
    dup = await anon_client.post(f"{SCIM}/Groups", json={"displayName": "engineering"}, headers=h)
    assert dup.status_code == 409
    r = await anon_client.patch(
        f"{SCIM}/Groups/{gid}",
        json=ops(
            {"op": "Add", "path": "members", "value": [{"value": u2}]},
            {"op": "Remove", "path": "members", "value": [{"value": u1}]},
        ),
        headers=h,
    )
    assert r.status_code == 200 and [m["value"] for m in r.json()["members"]] == [u2]
    r = await anon_client.patch(
        f"{SCIM}/Groups/{gid}",
        json=ops(
            {"op": "remove", "path": f'members[value eq "{u2}"]'},
            {"op": "replace", "value": {"id": gid, "displayName": "Eng"}},
        ),
        headers=h,
    )
    assert r.json()["displayName"] == "Eng" and r.json()["members"] == []
    listed = (
        await anon_client.get(
            f"{SCIM}/Groups",
            params={"filter": 'displayName eq "eng"', "excludedAttributes": "members"},
            headers=h,
        )
    ).json()
    assert listed["totalResults"] == 1 and "members" not in listed["Resources"][0]
    user = (await anon_client.get(f"{SCIM}/Users/{u2}", headers=h)).json()
    assert user["groups"] == []
    r = await anon_client.put(
        f"{SCIM}/Groups/{gid}",
        json={"displayName": "Eng", "members": [{"value": u1}, {"value": u2}]},
        headers=h,
    )
    assert len(r.json()["members"]) == 2
    user = (await anon_client.get(f"{SCIM}/Users/{u1}", headers=h)).json()
    assert user["groups"][0]["display"] == "Eng"
    assert (await anon_client.delete(f"{SCIM}/Groups/{gid}", headers=h)).status_code == 204
    assert (await anon_client.get(f"{SCIM}/Groups/{gid}", headers=h)).status_code == 404
    status = (await client.get("/orgs/acme/scim")).json()
    assert status["active_users"] == 2 and status["groups"] == []


async def test_group_role_mapping_follows_group_membership(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    gid = (
        await anon_client.post(
            f"{SCIM}/Groups",
            json={"displayName": "Builder Admins", "members": [{"value": uid}]},
            headers=h,
        )
    ).json()["id"]
    # No dictionary yet: groups don't change roles.
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.member
    r = await client.patch("/orgs/acme/scim", json={"group_roles": {"Builder Admins": "admin"}})
    assert r.status_code == 200
    assert r.json()["groups"] == [
        {"display_name": "Builder Admins", "members": 1, "mapped_role": "admin"}
    ]
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.admin
    await anon_client.patch(
        f"{SCIM}/Groups/{gid}", json=ops({"op": "remove", "path": "members"}), headers=h
    )
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.member
    await anon_client.patch(
        f"{SCIM}/Groups/{gid}",
        json=ops({"op": "add", "path": "members", "value": [{"value": uid}]}),
        headers=h,
    )
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.admin
    changed = await actions(session_factory, "scim.role_changed")
    assert [(c.detail["from"], c.detail["to"]) for c in changed] == [  # type: ignore[index]
        ("member", "admin"),
        ("admin", "member"),
        ("member", "admin"),
    ]
    await anon_client.delete(f"{SCIM}/Groups/{gid}", headers=h)
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.member
    # A new user who's in a mapped group joins with that role.
    await client.patch("/orgs/acme/scim", json={"group_roles": {"Owners": "owner"}})
    await anon_client.post(
        f"{SCIM}/Groups", json={"displayName": "owners", "members": [{"value": uid}]}, headers=h
    )
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.owner


async def test_directory_never_demotes_the_last_owner(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    await client.patch("/orgs/acme/scim", json={"group_roles": {"Owners": "owner"}})
    gid = (
        await anon_client.post(
            f"{SCIM}/Groups", json={"displayName": "Owners", "members": [{"value": uid}]}, headers=h
        )
    ).json()["id"]
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.owner
    async with session_factory() as s:  # the human owner leaves; Alice is the last owner
        m = await s.get(OrganizationMember, (uuid.UUID(org), client.user.id))  # type: ignore[attr-defined]
        assert m is not None
        m.role = OrgRole.member
        await s.commit()
    await anon_client.patch(
        f"{SCIM}/Groups/{gid}", json=ops({"op": "remove", "path": "members"}), headers=h
    )
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.owner


# == operator ===================================================================================


async def test_operator_sees_status_and_can_rotate_the_token_away(
    client: AsyncClient,
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    await provision(anon_client, h)
    staff = await client_for("ops@example.com", PlatformRole.platform_admin, sec.AUDIENCE_ADMIN)
    support = await client_for(
        "help@example.com", PlatformRole.platform_support, sec.AUDIENCE_ADMIN
    )
    from tests.api.conftest import bearer_for

    staff.headers.update(bearer_for(staff.user, sec.AUDIENCE_ADMIN, amr=["pwd", "otp"]))  # type: ignore[attr-defined]
    support.headers.update(bearer_for(support.user, sec.AUDIENCE_ADMIN, amr=["pwd", "otp"]))  # type: ignore[attr-defined]
    row = (await staff.get(f"/admin/organizations/{org}")).json()
    assert row["scim_configured"] is True and row["scim_active"] is True
    assert row["scim_users"] == 1 and row["scim_last_sync_at"] is not None
    listed = (await staff.get("/admin/organizations", params={"q": "acme"})).json()["items"]
    assert listed[0]["scim_active"] is True
    r = await support.post(f"/admin/organizations/{org}/scim/rotate", json={"reason": "leak"})
    assert r.status_code == 403
    r = await staff.post(f"/admin/organizations/{org}/scim/rotate", json={"reason": "token leaked"})
    assert r.status_code == 200, r.text
    assert r.json()["scim_active"] is False
    assert "token" not in r.text.lower().replace("scim_token", "")
    assert (await anon_client.get(f"{SCIM}/Users", headers=h)).status_code == 401
    logged = await actions(session_factory, "admin.scim_token_rotated")
    assert logged and logged[0].detail == {"reason": "token leaked"}
    # The org admin issues a fresh token; nobody else ever saw one.
    assert (await client.get("/orgs/acme/scim")).json()["token_hint"] is None
    # The operator only switched SCIM off so the unseen token can't be used: the admin's fresh
    # token switches it back on, with no second step.
    fresh = await scim_token(client)
    assert (await client.get("/orgs/acme/scim")).json()["active"] is True
    assert (await anon_client.get(f"{SCIM}/Users", headers=fresh)).status_code == 200
    r = await staff.post(f"/admin/organizations/{uuid.uuid4()}/scim/rotate", json={"reason": "x"})
    assert r.status_code == 404
