"""Operator "view as" tokens: look-only by default, never a way to credentials, other orgs, the
admin console, or to outlive the session / the operator / the member."""

import re
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_authz as authz
from app.models.enums import AccountStatus
from app.models.platform import ImpersonationSession, PlatformUser
from tests.api._routes import all_routes
from tests.api.conftest import ClientFor
from tests.api.test_impersonation import World, world  # noqa: F401 - `world` is a fixture

Factory = async_sessionmaker[AsyncSession]
DUMMY = "00000000-0000-4000-8000-000000000009"
WRITE = ("POST", "PUT", "PATCH", "DELETE")
OPEN = authz.IMPERSONATION_OPEN_ROUTES


def _fill(path: str, w: World) -> str:
    path = path.replace("{project_id}", w.project).replace("{slug}", "acme")
    path = path.replace("{domain}", "evil.example").replace("{metric}", "projects")
    return re.sub(r"{[^}]+}", DUMMY, path)


async def _walk(viewer: AsyncClient, w: World, methods: tuple[str, ...]) -> list[str]:
    bad = []
    for r in all_routes():
        if r.method not in methods or (r.method, r.path) in OPEN or r.path.startswith("/admin"):
            continue
        if not (r.names & {"guard", "org_context", "current_principal", "session_principal", "acting_principal"}):
            continue
        resp = await viewer.request(r.method, _fill(r.path, w), json={})
        if resp.status_code < 400 or resp.status_code >= 500:
            bad.append(f"{r.method} {r.path} -> {resp.status_code}")
    return bad


async def test_view_as_with_writes_off_cannot_change_anything(world: World) -> None:  # noqa: F811
    viewer, _ = await world.view_as()
    skip = {t for _, t in authz._READ_ONLY_POSTS}
    bad = [b for b in await _walk(viewer, world, WRITE) if b.split()[1] not in skip]
    assert bad == []
    assert (await world.owner.get(f"/projects/{world.project}")).status_code == 200


async def test_view_as_with_writes_on_still_blocks_credentials_members_org_console(world: World) -> None:  # noqa: F811
    viewer, _ = await world.view_as()
    assert (await viewer.post("/account/impersonation/writes", json={"enabled": True})).status_code == 200
    bad = []
    for m, p, body in (
        ("POST", f"/projects/{world.project}/tokens", {}),
        ("GET", f"/projects/{world.project}/tokens", None),
        ("PUT", f"/projects/{world.project}/auth/secrets", {}),
        ("GET", f"/projects/{world.project}/auth/secrets/status", None),
        ("GET", f"/projects/{world.project}/generate/download", None),
        ("POST", f"/projects/{world.project}/members", {"email": "evil@example.com", "role": "owner"}),
        ("PATCH", f"/projects/{world.project}/members/{world.owner.user.id}", {"role": "viewer"}),  # type: ignore[attr-defined]
        ("DELETE", f"/projects/{world.project}", None),
        ("POST", "/projects", {"name": "x"}),
        ("POST", "/orgs", {"name": "X", "slug": "xorg"}),
        ("PATCH", "/orgs/acme", {"name": "Hacked"}),
        ("DELETE", "/orgs/acme", None),
        ("POST", "/orgs/acme/invitations", {"email": "evil@example.com", "role": "owner"}),
        ("POST", "/orgs/acme/transfer", {"user_id": str(world.member.user.id)}),  # type: ignore[attr-defined]
        ("GET", "/orgs/acme/export", None),
        ("POST", "/account/tokens", {"name": "t", "scopes": ["write"]}),
        ("POST", "/account/logout-all", None),
        ("DELETE", "/account", None),
        ("GET", "/admin/users", None),
        ("POST", "/orgs/acme/billing/portal", None),
    ):
        r = await viewer.request(m, p, json=body) if body is not None else await viewer.request(m, p)
        if r.status_code < 400 or r.status_code >= 500:
            bad.append(f"{m} {p} -> {r.status_code}")
    assert bad == []
    assert (await world.owner.get(f"/projects/{world.project}")).status_code == 200
    assert (await world.owner.get("/orgs/acme")).json()["name"] == "Acme"


async def test_view_as_token_is_not_an_admin_token_and_not_another_orgs(
    world: World, client_for: ClientFor  # noqa: F811
) -> None:
    viewer, _ = await world.view_as()
    assert (await viewer.get("/admin/users")).status_code in (401, 403)
    other = await client_for("outsider@example.com")
    await other.post("/orgs", json={"name": "Other", "slug": "otherorg"})
    other_pid = (await other.post("/projects", json={"name": "Theirs"})).json()["id"]
    assert (await viewer.get(f"/projects/{other_pid}")).status_code == 404
    assert (await viewer.get("/orgs/otherorg")).status_code == 404
    slugs = [o["slug"] for o in (await viewer.get("/orgs")).json()["items"]]
    assert slugs == ["acme"]


async def test_ended_session_token_is_dead_and_replay_is_refused(world: World) -> None:  # noqa: F811
    viewer, body = await world.view_as()
    assert (await viewer.get(f"/projects/{world.project}")).status_code == 200
    assert (await viewer.post("/account/impersonation/end")).status_code == 204
    for _ in range(3):
        assert (await viewer.get(f"/projects/{world.project}")).status_code == 401
        assert (await viewer.get("/account/me")).status_code == 401
    r = await viewer.post("/account/impersonation/writes", json={"enabled": True})
    assert r.status_code == 401


async def test_expired_session_row_kills_the_token(world: World, session_factory: Factory) -> None:  # noqa: F811
    viewer, body = await world.view_as()
    async with session_factory() as s:
        await s.execute(
            update(ImpersonationSession)
            .where(ImpersonationSession.id == uuid.UUID(body["session_id"]))  # type: ignore[arg-type]
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert (await viewer.get(f"/projects/{world.project}")).status_code == 401


async def test_operator_loses_admin_role_kills_open_sessions(world: World, session_factory: Factory) -> None:  # noqa: F811
    viewer, _ = await world.view_as()
    assert (await viewer.get(f"/projects/{world.project}")).status_code == 200
    async with session_factory() as s:
        await s.execute(
            update(PlatformUser).where(PlatformUser.id == world.ops.user.id).values(platform_role="customer")  # type: ignore[attr-defined]
        )
        await s.commit()
    assert (await viewer.get(f"/projects/{world.project}")).status_code == 401


async def test_suspended_member_or_operator_kills_open_sessions(world: World, session_factory: Factory) -> None:  # noqa: F811
    viewer, _ = await world.view_as()
    async with session_factory() as s:
        await s.execute(update(PlatformUser).where(PlatformUser.id == world.owner.user.id).values(status=AccountStatus.suspended))  # type: ignore[attr-defined]
        await s.commit()
    assert (await viewer.get(f"/projects/{world.project}")).status_code == 401


async def test_cannot_view_as_a_platform_admin_or_an_outsider(world: World, client_for: ClientFor) -> None:  # noqa: F811
    outsider = await client_for("out@example.com")
    r = await world.ops.post(
        f"/admin/organizations/{world.org_id}/members/{outsider.user.id}/impersonate",  # type: ignore[attr-defined]
        json={"reason": "ticket 5512"},
    )
    assert r.status_code in (404, 409, 422), r.text
    r = await world.ops.post(
        f"/admin/organizations/{world.org_id}/members/{world.ops.user.id}/impersonate",  # type: ignore[attr-defined]
        json={"reason": "ticket 5512"},
    )
    assert r.status_code in (404, 409, 422, 403), r.text


async def test_support_role_and_customer_cannot_start_a_session(world: World, client_for: ClientFor) -> None:  # noqa: F811
    from app.core import platform_security as sec
    from app.models.enums import PlatformRole

    support = await client_for("support@example.com", PlatformRole.platform_support, audience=sec.AUDIENCE_ADMIN)
    url = f"/admin/organizations/{world.org_id}/members/{world.owner.user.id}/impersonate"  # type: ignore[attr-defined]
    assert (await support.post(url, json={"reason": "ticket 1234"})).status_code == 403
    assert (await world.member.post(url, json={"reason": "ticket 1234"})).status_code in (401, 403)
    assert (await world.owner.post(url, json={"reason": "ticket 1234"})).status_code in (401, 403)


async def test_reason_is_mandatory_and_bounded(world: World) -> None:  # noqa: F811
    url = f"/admin/organizations/{world.org_id}/members/{world.owner.user.id}/impersonate"  # type: ignore[attr-defined]
    for body in ({}, {"reason": ""}, {"reason": "  "}, {"reason": "x" * 100_000}, {"reason": None}):
        r = await world.ops.post(url, json=body)
        assert r.status_code in (400, 422), (str(body)[:30], r.status_code)


async def test_writes_switch_requires_a_real_boolean_and_expires(world: World, session_factory: Factory) -> None:  # noqa: F811
    viewer, body = await world.view_as()
    for bad in ({"enabled": "maybe"}, {}, {"enabled": None}, {"enabled": [True]}):
        assert (await viewer.post("/account/impersonation/writes", json=bad)).status_code == 422
    assert (await viewer.post("/account/impersonation/writes", json={"enabled": True})).status_code == 200
    async with session_factory() as s:
        await s.execute(
            update(ImpersonationSession)
            .where(ImpersonationSession.id == uuid.UUID(body["session_id"]))  # type: ignore[arg-type]
            .values(writes_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    r = await viewer.post(f"/projects/{world.project}/entities", json={"name": "AfterExpiry"})
    assert r.status_code == 403 and r.json()["code"] == "impersonation_read_only"
