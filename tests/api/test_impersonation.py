"""Impersonation (PLATFORM_SAAS_PLAN §4.5, §7.1, §8), Phase F.

An operator presses "View as" on an org member; the server mints a short-lived token for that
member that names a database session row. Every request is audited, writes are off unless the
operator flips a short, audited switch, and an org that withdrew consent cuts the session off at
once. A viewing token never reaches the account, credentials, billing, export or other orgs.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_security as sec
from app.main import app
from app.models.enums import OrgRole, PlatformRole
from app.models.platform import (
    AuditLog,
    ImpersonationSession,
    Organization,
    OrganizationMember,
    PlatformUser,
)
from tests.api._auth_helpers import make_entity
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]


class World:
    def __init__(self) -> None:
        self.owner: AsyncClient
        self.member: AsyncClient
        self.ops: AsyncClient
        self.org_id: str
        self.project: str
        self.viewers: list[AsyncClient] = []

    async def view_as(
        self, user: AsyncClient | None = None, reason: str = "ticket 4411"
    ) -> tuple[AsyncClient, dict[str, object]]:
        target = user or self.owner
        r = await self.ops.post(
            f"/admin/organizations/{self.org_id}/members/{target.user.id}/impersonate",  # type: ignore[attr-defined]
            json={"reason": reason},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        viewer = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        self.viewers.append(viewer)
        return viewer, body


@pytest.fixture
async def world(client_for: ClientFor) -> World:
    w = World()
    w.owner = await client_for("owner@example.com")
    w.member = await client_for("bob@example.com")
    w.ops = await client_for(
        "ops@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )
    created = await w.owner.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert created.status_code == 201, created.text
    w.org_id = created.json()["id"]
    inv = await w.owner.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    assert inv.status_code == 201, inv.text
    accepted = await w.member.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    assert accepted.status_code == 200, accepted.text
    project = await w.owner.post("/projects", json={"name": "App", "organization_id": w.org_id})
    assert project.status_code == 201, project.text
    w.project = project.json()["id"]
    await make_entity(w.owner, w.project, "Customer")
    yield w  # type: ignore[misc]
    for v in w.viewers:
        await v.aclose()


async def _audit(factory: Factory, prefix: str = "impersonation.") -> list[AuditLog]:
    async with factory() as s:
        rows = await s.execute(
            select(AuditLog).where(AuditLog.action.startswith(prefix)).order_by(AuditLog.id)
        )
        return list(rows.scalars())


async def _session_row(factory: Factory, sid: str) -> ImpersonationSession:
    async with factory() as s:
        row = await s.get(ImpersonationSession, uuid.UUID(sid))
        assert row is not None
        return row


# -- starting a session ------------------------------------------------------------------------


async def test_an_admin_starts_a_session_and_the_token_works(
    world: World, session_factory: Factory
) -> None:
    viewer, body = await world.view_as()
    assert body["expires_in"] == 600  # §4.5: ten minutes
    assert body["organization_slug"] == "acme" and body["user_email"] == "owner@example.com"
    me = await viewer.get("/orgs/acme")
    assert me.status_code == 200 and me.json()["my_role"] == "owner"
    state = await viewer.get("/account/impersonation")
    assert state.status_code == 200
    s = state.json()
    assert s["operator_email"] == "ops@example.com" and s["writes_allowed"] is False
    assert s["organization_slug"] == "acme" and s["user_email"] == "owner@example.com"
    started = (await _audit(session_factory, "impersonation.started"))[0]
    assert started.actor_email == "ops@example.com" and started.organization_id == uuid.UUID(
        world.org_id
    )
    assert started.target_id == str(world.owner.user.id)  # type: ignore[attr-defined]
    assert (started.detail or {}).get("reason") == "ticket 4411"


async def test_the_token_is_never_written_to_the_audit_log(
    world: World, session_factory: Factory
) -> None:
    viewer, body = await world.view_as()
    await viewer.get("/orgs/acme")
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog))).scalars().all()
    for row in rows:
        assert str(body["access_token"]) not in repr(row.detail) + repr(row.target_id)
    listed = await world.ops.get("/admin/impersonation/sessions")
    assert str(body["access_token"]) not in listed.text


async def test_only_platform_admins_may_impersonate(world: World, client_for: ClientFor) -> None:
    support = await client_for(
        "help@example.com", PlatformRole.platform_support, audience=sec.AUDIENCE_ADMIN
    )
    url = f"/admin/organizations/{world.org_id}/members/{world.owner.user.id}/impersonate"  # type: ignore[attr-defined]
    assert (await support.post(url, json={"reason": "just looking"})).status_code == 403
    assert (await world.owner.post(url, json={"reason": "just looking"})).status_code == 401
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    assert (await anon.post(url, json={"reason": "just looking"})).status_code == 401
    await anon.aclose()


async def test_a_reason_is_required(world: World) -> None:
    url = f"/admin/organizations/{world.org_id}/members/{world.owner.user.id}/impersonate"  # type: ignore[attr-defined]
    assert (await world.ops.post(url, json={})).status_code == 422
    assert (await world.ops.post(url, json={"reason": "  "})).status_code == 422


async def test_only_members_of_that_org_who_are_not_staff(
    world: World, client_for: ClientFor, session_factory: Factory
) -> None:
    stranger = await client_for("stranger@example.com")
    base = f"/admin/organizations/{world.org_id}/members"
    reason = {"reason": "peek here"}
    assert (
        await world.ops.post(f"{base}/{stranger.user.id}/impersonate", json=reason)
    ).status_code == 404  # type: ignore[attr-defined]
    assert (
        await world.ops.post(f"{base}/{uuid.uuid4()}/impersonate", json=reason)
    ).status_code == 404
    # A staff account that sits in the org (support staff are sometimes added as members) is
    # still never viewed as - not by another admin, not by itself.
    other_admin = await client_for(
        "ops2@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )
    for staff in (world.ops.user, other_admin.user):  # type: ignore[attr-defined]
        async with session_factory() as s:
            s.add(
                OrganizationMember(
                    organization_id=uuid.UUID(world.org_id), user_id=staff.id, role=OrgRole.member
                )
            )
            await s.commit()
        for actor in (world.ops, other_admin):
            r = await actor.post(f"{base}/{staff.id}/impersonate", json=reason)
            assert r.status_code == 404, r.text


# -- consent (§7.1) ----------------------------------------------------------------------------


async def test_consent_defaults_on_and_an_org_can_withdraw_it(
    world: World, session_factory: Factory
) -> None:
    policies = await world.owner.get("/orgs/acme/policies")
    assert policies.json()["allow_impersonation"] is True
    off = await world.owner.patch("/orgs/acme/policies", json={"allow_impersonation": False})
    assert off.status_code == 200 and off.json()["allow_impersonation"] is False
    url = f"/admin/organizations/{world.org_id}/members/{world.owner.user.id}/impersonate"  # type: ignore[attr-defined]
    refused = await world.ops.post(url, json={"reason": "customer asked"})
    assert refused.status_code == 403 and refused.json()["code"] == "impersonation_disabled"
    denied = [a for a in await _audit(session_factory, "impersonation.denied")]
    assert denied and denied[0].organization_id == uuid.UUID(world.org_id)
    changed = await _audit(session_factory, "org.policy_changed")
    assert any((a.detail or {}).get("allow_impersonation") is False for a in changed)


async def test_members_cannot_change_the_consent_policy(world: World) -> None:
    r = await world.member.patch("/orgs/acme/policies", json={"allow_impersonation": False})
    assert r.status_code == 403


async def test_withdrawing_consent_ends_a_running_session_at_once(
    world: World, session_factory: Factory
) -> None:
    viewer, body = await world.view_as()
    assert (await viewer.get("/orgs/acme")).status_code == 200
    await world.owner.patch("/orgs/acme/policies", json={"allow_impersonation": False})
    assert (await viewer.get("/orgs/acme")).status_code == 401
    assert (await viewer.get(f"/projects/{world.project}")).status_code == 401
    row = await _session_row(session_factory, str(body["session_id"]))
    assert row.ended_at is not None
    assert any(
        (a.detail or {}).get("why") == "consent_withdrawn"
        for a in await _audit(session_factory, "impersonation.ended")
    )


# -- every request is logged -------------------------------------------------------------------


async def test_reads_are_audited_as_impersonation(world: World, session_factory: Factory) -> None:
    viewer, _ = await world.view_as()
    assert (await viewer.get(f"/projects/{world.project}/entities")).status_code == 200
    rows = [a for a in await _audit(session_factory, "impersonation.request")]
    assert rows
    last = rows[-1]
    assert last.via == "impersonation" and last.organization_id == uuid.UUID(world.org_id)
    assert last.actor_id == world.owner.user.id  # type: ignore[attr-defined]
    detail = last.detail or {}
    assert detail["impersonator_id"] == str(world.ops.user.id)  # type: ignore[attr-defined]
    assert detail["method"] == "GET"


# -- writes are blocked unless switched on -----------------------------------------------------


async def test_writes_are_blocked_by_default(world: World) -> None:
    viewer, _ = await world.view_as()
    r = await viewer.patch(f"/projects/{world.project}", json={"name": "Hacked", "version": 1})
    assert r.status_code == 403 and r.json()["code"] == "impersonation_read_only"
    assert (
        await viewer.post(f"/projects/{world.project}/entities", json={"name": "X"})
    ).status_code == 403
    # reading is unaffected, and the project is untouched
    assert (await world.owner.get(f"/projects/{world.project}")).json()["name"] == "App"


async def test_the_allow_writes_switch_is_short_audited_and_reversible(
    world: World, session_factory: Factory
) -> None:
    viewer, body = await world.view_as()
    on = await viewer.post("/account/impersonation/writes", json={"enabled": True})
    assert on.status_code == 200 and on.json()["writes_allowed"] is True
    until = datetime.fromisoformat(on.json()["writes_until"])
    assert timedelta(minutes=4) < until - datetime.now(UTC) <= timedelta(minutes=5, seconds=2)
    ok = await viewer.post(f"/projects/{world.project}/entities", json={"name": "Invoice"})
    assert ok.status_code == 201, ok.text
    change = [
        a for a in await _audit(session_factory, "project.change") if a.via == "impersonation"
    ]
    assert change and (change[-1].detail or {})["impersonator_id"] == str(world.ops.user.id)  # type: ignore[attr-defined]
    assert any(a.action == "impersonation.writes_enabled" for a in await _audit(session_factory))
    off = await viewer.post("/account/impersonation/writes", json={"enabled": False})
    assert off.json()["writes_allowed"] is False
    assert (
        await viewer.post(f"/projects/{world.project}/entities", json={"name": "Again"})
    ).status_code == 403
    assert any(a.action == "impersonation.writes_disabled" for a in await _audit(session_factory))
    assert body["session_id"]


async def test_the_switch_runs_out(world: World, session_factory: Factory) -> None:
    viewer, body = await world.view_as()
    await viewer.post("/account/impersonation/writes", json={"enabled": True})
    async with session_factory() as s:
        row = await s.get(ImpersonationSession, uuid.UUID(str(body["session_id"])))
        assert row is not None
        row.writes_until = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    assert (
        await viewer.post(f"/projects/{world.project}/entities", json={"name": "Late"})
    ).status_code == 403


# -- what a viewing token can never do ----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/projects/{p}/tokens", None),
        ("PUT", "/projects/{p}/auth/secrets", {}),
        ("GET", "/projects/{p}/auth/secrets/status", None),
        ("GET", "/projects/{p}/generate/download", None),
        ("POST", "/projects/{p}/members", {"email": "x@example.com", "role": "viewer"}),
        ("DELETE", "/projects/{p}", None),
        ("POST", "/projects", {"name": "Nope"}),
        ("PATCH", "/orgs/acme", {"name": "Renamed"}),
        ("PATCH", "/orgs/acme/policies", {"require_mfa": True}),
        ("DELETE", "/orgs/acme", None),
        ("POST", "/orgs/acme/invitations", {"email": "n@example.com", "role": "member"}),
        ("POST", "/orgs/acme/billing/checkout", {}),
        ("GET", "/orgs/acme/export", None),
        ("POST", "/orgs", {"name": "Evil", "slug": "evil"}),
        ("POST", "/orgs/invitations/accept", {"token": "x"}),
        ("PUT", "/account/me/default-organization", {"organization_id": str(uuid.uuid4())}),
        ("POST", "/account/password", {"current_password": "a", "new_password": "b"}),
        ("GET", "/account/tokens", None),
        ("POST", "/account/tokens", {"name": "x"}),
        ("GET", "/account/mfa", None),
        ("POST", "/account/logout-all", None),
    ],
)
async def test_a_viewing_token_never_reaches_credentials_billing_export_or_destructive_actions(
    world: World, method: str, path: str, body: dict[str, object] | None
) -> None:
    viewer, _ = await world.view_as()
    await viewer.post(
        "/account/impersonation/writes", json={"enabled": True}
    )  # even with writes on
    r = await viewer.request(method, path.replace("{p}", world.project), json=body)
    assert r.status_code == 403, f"{method} {path} -> {r.status_code} {r.text}"


async def test_a_viewing_token_cannot_leave_the_org(world: World) -> None:
    viewer, _ = await world.view_as()
    mine = await world.owner.get("/orgs")
    personal = next(o for o in mine.json()["items"] if o["kind"] == "personal")
    other = (
        await world.owner.post(
            "/projects", json={"name": "Elsewhere", "organization_id": personal["id"]}
        )
    ).json()["id"]
    assert (await viewer.get(f"/orgs/{personal['slug']}")).status_code == 404
    assert (await viewer.get(f"/projects/{other}")).status_code == 404
    orgs = (await viewer.get("/orgs")).json()["items"]
    assert [o["slug"] for o in orgs] == ["acme"]
    projects = (await viewer.get("/projects")).json()["items"]
    assert [p["name"] for p in projects] == ["App"]


# -- ending, expiry, the operator ----------------------------------------------------------------


async def test_the_customer_side_can_end_the_session(
    world: World, session_factory: Factory
) -> None:
    viewer, body = await world.view_as()
    assert (await viewer.post("/account/impersonation/end")).status_code == 204
    assert (await viewer.get("/orgs/acme")).status_code == 401
    assert (await _session_row(session_factory, str(body["session_id"]))).ended_at is not None
    assert any(a.action == "impersonation.ended" for a in await _audit(session_factory))


async def test_the_operator_can_end_it_and_the_list_shows_it(world: World) -> None:
    viewer, body = await world.view_as()
    listed = await world.ops.get("/admin/impersonation/sessions")
    assert listed.status_code == 200
    first = listed.json()["items"][0]
    assert first["id"] == body["session_id"] and first["active"] is True
    assert first["operator_email"] == "ops@example.com" and first["reason"] == "ticket 4411"
    assert (
        await world.ops.post(f"/admin/impersonation/sessions/{body['session_id']}/end")
    ).status_code == 204
    assert (await viewer.get("/orgs/acme")).status_code == 401
    assert (await world.ops.get("/admin/impersonation/sessions")).json()["items"][0][
        "active"
    ] is False


async def test_an_expired_session_row_kills_the_token(
    world: World, session_factory: Factory
) -> None:
    viewer, body = await world.view_as()
    async with session_factory() as s:
        row = await s.get(ImpersonationSession, uuid.UUID(str(body["session_id"])))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    assert (await viewer.get("/orgs/acme")).status_code == 401


async def test_a_suspended_or_demoted_operator_loses_the_session(
    world: World, session_factory: Factory
) -> None:
    viewer, _ = await world.view_as()
    async with session_factory() as s:
        ops = await s.get(PlatformUser, world.ops.user.id)  # type: ignore[attr-defined]
        assert ops is not None
        ops.platform_role = PlatformRole.platform_support
        await s.commit()
    assert (await viewer.get("/orgs/acme")).status_code == 401


async def test_the_target_losing_membership_ends_the_view(
    world: World, session_factory: Factory
) -> None:
    viewer, _ = await world.view_as(world.member)
    assert (await viewer.get("/orgs/acme")).status_code == 200
    r = await world.owner.delete(f"/orgs/acme/members/{world.member.user.id}")  # type: ignore[attr-defined]
    assert r.status_code == 204, r.text
    assert (await viewer.get("/orgs/acme")).status_code == 401


async def test_ordinary_sessions_have_no_impersonation_state(world: World) -> None:
    assert (await world.owner.get("/account/impersonation")).status_code == 404
    assert (
        await world.owner.post("/account/impersonation/writes", json={"enabled": True})
    ).status_code == 404
    assert (await world.owner.post("/account/impersonation/end")).status_code == 404


async def test_the_member_who_is_viewed_sees_it_in_their_org_audit(world: World) -> None:
    await world.view_as(world.member)
    audit = await world.owner.get("/orgs/acme/audit?action=impersonation.")
    assert audit.status_code == 200
    actions = [e["action"] for e in audit.json()["items"]]
    assert "impersonation.started" in actions


async def test_the_operator_org_view_shows_whether_the_org_consents(world: World) -> None:
    before = await world.ops.get(f"/admin/organizations/{world.org_id}")
    assert before.json()["allow_impersonation"] is True
    await world.owner.patch("/orgs/acme/policies", json={"allow_impersonation": False})
    after = await world.ops.get(f"/admin/organizations/{world.org_id}")
    assert after.json()["allow_impersonation"] is False
    listed = await world.ops.get("/admin/organizations")
    assert {o["slug"]: o["allow_impersonation"] for o in listed.json()["items"]}["acme"] is False


async def test_forged_tokens_naming_a_real_session_are_refused(world: World) -> None:
    """The token only names a session; the row binds it to one member and one operator."""
    _, body = await world.view_as()
    sid, operator = str(body["session_id"]), str(world.ops.user.id)  # type: ignore[attr-defined]
    bob = world.member.user  # type: ignore[attr-defined]

    def forged(user: PlatformUser, session: str, by: str) -> str:
        return sec.encode_jwt(
            sec.access_claims(
                user_id=str(user.id),
                audience=sec.AUDIENCE_APP,
                token_version=user.token_version,
                ttl_seconds=600,
                amr=["pwd", "otp"],
                extra={"imp_sid": session, "imp_by": by},
            )
        )

    cases = {
        "another member under the same session": forged(bob, sid, operator),
        "wrong operator": forged(world.owner.user, sid, str(uuid.uuid4())),  # type: ignore[attr-defined]
        "unknown session": forged(world.owner.user, str(uuid.uuid4()), operator),  # type: ignore[attr-defined]
        "not a session id": forged(world.owner.user, "nope", operator),  # type: ignore[attr-defined]
    }
    for name, token in cases.items():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            assert (await c.get("/orgs/acme")).status_code == 401, name


async def test_consent_is_rechecked_on_every_request_not_only_when_the_policy_is_saved(
    world: World, session_factory: Factory
) -> None:
    """Belt and braces: even if the flag flips without the API's session clean-up (a data fix,
    another code path), a running session stops at its next request."""
    viewer, _ = await world.view_as()
    assert (await viewer.get("/orgs/acme")).status_code == 200
    async with session_factory() as s:
        org = await s.get(Organization, uuid.UUID(world.org_id))
        assert org is not None
        org.allow_impersonation = False
        await s.commit()
    assert (await viewer.get("/orgs/acme")).status_code == 401
