"""Phase B — plan enforcement and seat accounting (PLATFORM_SAAS_PLAN §6.2, §12.B).

Every counter in the §6.2 table gets a test at its enforcement point. Each denial must be
a 402 that names the plan and the cap, and must leave a `quota.denied` audit row: auditors
look for the deny entry, so a refusal is never silent.
"""

import asyncio
import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.platform import AuditLog, Organization, Subscription
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]


async def _org_id(client: AsyncClient, slug: str | None = None) -> uuid.UUID:
    """The personal org (slug=None) or the org with this slug, as seen by `client`."""
    items = (await client.get("/orgs")).json()["items"]
    for org in items:
        if (slug is None and org["kind"] == "personal") or org["slug"] == slug:
            return uuid.UUID(org["id"])
    raise AssertionError(f"org {slug!r} not visible to this client")


async def _set_plan(
    factory: Factory,
    org_id: uuid.UUID,
    plan_id: str,
    *,
    seat_override: int | None = None,
    project_override: int | None = None,
) -> None:
    async with factory() as session:
        sub = await session.get(Subscription, org_id)
        assert sub is not None
        sub.plan_id = plan_id
        sub.seat_override = seat_override
        sub.project_override = project_override
        await session.commit()


async def _denials(factory: Factory, org_id: uuid.UUID) -> list[AuditLog]:
    async with factory() as session:
        rows = await session.execute(
            select(AuditLog).where(
                AuditLog.action == "quota.denied", AuditLog.organization_id == org_id
            )
        )
        return list(rows.scalars())


def _assert_quota_error(r, code: str, plan: str, cap: int) -> None:  # noqa: ANN001
    assert r.status_code == 402, r.text
    body = r.json()
    assert body["code"] == code
    assert body["details"], "the UI needs plan/cap details to render an upgrade CTA"
    detail = body["details"][0]
    assert detail["plan"] == plan
    assert detail["cap"] == cap
    assert detail["organization_slug"]  # the UI links to /#/org/<slug>/plan


# -- projects ----------------------------------------------------------------------------


async def test_project_cap_is_enforced_on_create(
    client: AsyncClient, session_factory: Factory
) -> None:
    org_id = await _org_id(client)
    await _set_plan(session_factory, org_id, "free")  # free: 1 project

    assert (await client.post("/projects", json={"name": "One"})).status_code == 201
    r = await client.post("/projects", json={"name": "Two"})
    _assert_quota_error(r, "project_limit", "free", 1)

    denials = await _denials(session_factory, org_id)
    assert len(denials) == 1
    assert denials[0].detail["resource"] == "projects"


async def test_project_override_lifts_the_cap(
    client: AsyncClient, session_factory: Factory
) -> None:
    org_id = await _org_id(client)
    await _set_plan(session_factory, org_id, "free", project_override=2)

    assert (await client.post("/projects", json={"name": "One"})).status_code == 201
    assert (await client.post("/projects", json={"name": "Two"})).status_code == 201
    r = await client.post("/projects", json={"name": "Three"})
    _assert_quota_error(r, "project_limit", "free", 2)


# -- API tokens --------------------------------------------------------------------------


async def test_api_token_cap_per_user_per_org(
    client: AsyncClient, session_factory: Factory
) -> None:
    org_id = await _org_id(client)
    await _set_plan(session_factory, org_id, "free")  # free: 3 API tokens

    ids = []
    for i in range(3):
        r = await client.post("/account/tokens", json={"name": f"t{i}", "scopes": ["read"]})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    r = await client.post("/account/tokens", json={"name": "t3", "scopes": ["read"]})
    _assert_quota_error(r, "api_token_limit", "free", 3)
    assert len(await _denials(session_factory, org_id)) == 1

    # A revoked token frees its slot.
    assert (await client.delete(f"/account/tokens/{ids[0]}")).status_code == 204
    r = await client.post("/account/tokens", json={"name": "t4", "scopes": ["read"]})
    assert r.status_code == 201


async def test_token_pinned_to_a_project_counts_against_that_projects_org(
    client: AsyncClient, session_factory: Factory
) -> None:
    """Tokens are counted per org: a full personal org must not block tokens in a team org."""
    personal = await _org_id(client)
    await _set_plan(session_factory, personal, "free")
    for i in range(3):
        r = await client.post("/account/tokens", json={"name": f"p{i}", "scopes": ["read"]})
        assert r.status_code == 201

    assert (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).status_code == 201
    acme = await _org_id(client, "acme")
    await _set_plan(session_factory, acme, "team")
    # Create a project inside acme directly (the API creates in the default org).
    from app.models.enums import MemberRole
    from app.models.platform import ProjectMember
    from app.models.project import Project

    async with session_factory() as session:
        project = Project(name="AcmeApp", slug="acme-app", organization_id=acme)
        session.add(project)
        await session.flush()
        session.add(
            ProjectMember(project_id=project.id, user_id=client.user.id, role=MemberRole.owner)  # type: ignore[attr-defined]
        )
        await session.commit()
        project_id = str(project.id)

    r = await client.post(
        "/account/tokens",
        json={"name": "acme", "scopes": ["read"], "project_id": project_id},
    )
    assert r.status_code == 201, r.text


async def test_mcp_tokens_are_capped_per_org(client: AsyncClient, session_factory: Factory) -> None:
    org_id = await _org_id(client)
    await _set_plan(session_factory, org_id, "free")  # free: 0 MCP tokens

    r = await client.post("/account/tokens", json={"name": "m", "scopes": ["mcp:read"]})
    _assert_quota_error(r, "mcp_token_limit", "free", 0)

    # Plain tokens are still allowed — only the MCP counter is full.
    r = await client.post("/account/tokens", json={"name": "plain", "scopes": ["read"]})
    assert r.status_code == 201


async def test_mcp_cap_counts_tokens_of_every_member(
    client_for: ClientFor, session_factory: Factory
) -> None:
    """The MCP counter is per org, not per user: two users' tokens share one cap."""
    owner = await client_for("owner@example.com")
    assert (await owner.post("/orgs", json={"name": "Acme", "slug": "acme"})).status_code == 201
    acme = await _org_id(owner, "acme")
    await _set_plan(session_factory, acme, "team")  # team: 5 MCP tokens

    from app.models.enums import MemberRole
    from app.models.platform import ProjectMember
    from app.models.project import Project

    bob = await client_for("bob@example.com")
    invite = await owner.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    assert invite.status_code == 201
    assert (
        await bob.post("/orgs/invitations/accept", json={"token": invite.json()["token"]})
    ).status_code == 200

    async with session_factory() as session:
        project = Project(name="AcmeApp", slug="acme-app", organization_id=acme)
        session.add(project)
        await session.flush()
        for user in (owner.user, bob.user):  # type: ignore[attr-defined]
            session.add(
                ProjectMember(project_id=project.id, user_id=user.id, role=MemberRole.owner)
            )
        await session.commit()
        pid = str(project.id)

    body = {"scopes": ["mcp:read"], "project_id": pid}
    for i in range(3):
        assert (
            await owner.post("/account/tokens", json={"name": f"o{i}", **body})
        ).status_code == 201
    for i in range(2):
        assert (
            await bob.post("/account/tokens", json={"name": f"b{i}", **body})
        ).status_code == 201
    r = await bob.post("/account/tokens", json={"name": "b2", **body})
    _assert_quota_error(r, "mcp_token_limit", "team", 5)


# -- seats -------------------------------------------------------------------------------


async def test_accept_rechecks_the_seat_cap(
    client_for: ClientFor, session_factory: Factory
) -> None:
    """An admin lowers the cap between invite and accept: the accept must refuse."""
    owner = await client_for("owner@example.com")
    assert (await owner.post("/orgs", json={"name": "Acme", "slug": "acme"})).status_code == 201
    acme = await _org_id(owner, "acme")
    invite = await owner.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    assert invite.status_code == 201

    await _set_plan(session_factory, acme, "team", seat_override=1)

    bob = await client_for("bob@example.com")
    r = await bob.post("/orgs/invitations/accept", json={"token": invite.json()["token"]})
    _assert_quota_error(r, "seat_limit", "team", 1)
    members = (await owner.get("/orgs/acme/members")).json()
    assert members["total"] == 1
    assert len(await _denials(session_factory, acme)) == 1

    # Raising the cap again lets the same invite through.
    await _set_plan(session_factory, acme, "team", seat_override=2)
    r = await bob.post("/orgs/invitations/accept", json={"token": invite.json()["token"]})
    assert r.status_code == 200


async def test_invite_denial_is_audited(client: AsyncClient, session_factory: Factory) -> None:
    assert (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).status_code == 201
    acme = await _org_id(client, "acme")
    await _set_plan(session_factory, acme, "team", seat_override=1)
    r = await client.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    _assert_quota_error(r, "seat_limit", "team", 1)
    denials = await _denials(session_factory, acme)
    assert [d.detail["resource"] for d in denials] == ["seats"]


async def test_concurrent_invites_cannot_exceed_the_cap(
    client: AsyncClient, session_factory: Factory
) -> None:
    """§6.2: the subscription row is locked, so a double-click cannot overshoot the cap."""
    assert (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).status_code == 201
    acme = await _org_id(client, "acme")
    await _set_plan(session_factory, acme, "team", seat_override=2)  # owner + exactly 1 more

    results = await asyncio.gather(
        *[
            client.post(
                "/orgs/acme/invitations",
                json={"email": f"user{i}@example.com", "role": "member"},
            )
            for i in range(5)
        ]
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 402, 402, 402, 402], [r.text for r in results]


async def test_concurrent_project_creates_cannot_exceed_the_cap(
    client: AsyncClient, session_factory: Factory
) -> None:
    org_id = await _org_id(client)
    await _set_plan(session_factory, org_id, "free")
    results = await asyncio.gather(
        *[client.post("/projects", json={"name": f"P{i}"}) for i in range(4)]
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 402, 402, 402], [r.text for r in results]


# -- usage reported to the UI ----------------------------------------------------------


async def test_plan_usage_reports_every_counter(
    client: AsyncClient, session_factory: Factory
) -> None:
    org_id = await _org_id(client)
    await _set_plan(session_factory, org_id, "team")
    await client.post("/projects", json={"name": "One"})
    await client.post("/account/tokens", json={"name": "a", "scopes": ["read"]})
    await client.post("/account/tokens", json={"name": "m", "scopes": ["mcp:read"]})

    slug = (await client.get("/orgs")).json()["items"][0]["slug"]
    usage = (await client.get(f"/orgs/{slug}/plan")).json()["usage"]
    assert usage["projects_used"] == 1
    assert usage["projects_cap"] == 10
    assert usage["seats_used"] == 1
    assert usage["seats_cap"] == 5
    assert usage["api_tokens_used"] == 2  # the viewer's own tokens in this org
    assert usage["api_tokens_cap"] == 20
    assert usage["mcp_tokens_used"] == 1
    assert usage["mcp_tokens_cap"] == 5


async def test_the_quota_is_not_bypassed_by_an_unknown_org(
    client: AsyncClient, session_factory: Factory
) -> None:
    """Sanity: an org whose subscription row is missing fails closed, never open."""
    org_id = await _org_id(client)
    async with session_factory() as session:
        sub = await session.get(Subscription, org_id)
        await session.delete(sub)
        await session.commit()
    r = await client.post("/projects", json={"name": "One"})
    assert r.status_code in (402, 404)
    async with session_factory() as session:
        org = await session.get(Organization, org_id)
        assert org is not None


# -- review F-011: a refusal names who was refused ----------------------------------------------


async def test_quota_denied_audit_rows_carry_the_actor_address(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = (await client.post("/orgs", json={"name": "Free", "slug": "free-co"})).json()
    await _set_plan(session_factory, org["id"], "free")
    one = await client.post("/projects", json={"name": "a", "organization_id": org["id"]})
    two = await client.post("/projects", json={"name": "b", "organization_id": org["id"]})
    seat = await client.post(
        "/orgs/free-co/invitations", json={"email": "x@example.com", "role": "member"}
    )
    assert one.status_code == 201 and two.status_code == 402 and seat.status_code == 402
    audit = (await client.get("/orgs/free-co/audit", params={"action": "quota.denied"})).json()
    rows = audit["items"]
    assert len(rows) >= 2
    assert {r["actor_email"] for r in rows} == {"primary@example.com"}
