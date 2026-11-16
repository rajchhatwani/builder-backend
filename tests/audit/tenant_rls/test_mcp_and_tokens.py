"""MCP service and API-token paths: the bearer carries no org binding, so each path must re-check
org membership itself."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_authz as authz
from app.exceptions import AppError
from app.models.enums import MemberRole, TokenAudience
from app.models.platform import ProjectMember
from app.services.access_service import Principal
from app.services.mcp_service import McpService
from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor
from tests.audit.tenant_rls._world import two_orgs, uid
from tests.audit.tenant_rls.test_org_attacks import _add_member, _mk, _team_org


def _principal(user: object, pinned: uuid.UUID | None = None) -> Principal:
    return Principal(
        user=user, via="api_token", audience=TokenAudience.app,  # type: ignore[arg-type]
        scopes=frozenset({authz.SCOPE_MCP_READ}), token_project_id=pinned,
    )


async def test_mcp_list_projects_hides_projects_of_an_org_the_user_left(
    client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """An mcp-enabled project_members row that outlives the org membership (any path that removes
    the org row only) must not keep listing the project's name/slug/description over MCP."""
    a, b = await two_orgs(client_for)
    await _team_org(a, "victimco")
    pid = await _mk(a, "victimco", "TopSecretProjectName")
    async with session_factory() as s:
        s.add(ProjectMember(project_id=uid(pid), user_id=b.user.id, role=MemberRole.editor, mcp_enabled=True))  # type: ignore[attr-defined]
        await s.commit()
    async with session_factory() as s:
        svc = McpService(s)
        try:
            listed = await svc.list_projects(_principal(b.user))  # type: ignore[attr-defined]
        except AppError:
            listed = []
        assert "TopSecretProjectName" not in str(listed), "list_projects skips the org-membership check"
        try:
            spec = await svc.get_project_spec(_principal(b.user), uid(pid))  # type: ignore[attr-defined]
            assert False, f"spec leaked: {str(spec)[:80]}"
        except AppError as exc:
            assert exc.status_code == 404


async def test_pinned_token_of_a_member_of_two_projects_stays_on_its_project(
    client_for: ClientFor,
) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    a = await client_for("victim@example.com")
    p1 = await make_project(a, "One")
    p2 = await make_project(a, "Two")
    await make_entity(a, p2, "OnlyInTwo")
    tok = await a.post("/account/tokens", json={"name": "pin", "scopes": ["write"], "project_id": p1})
    assert tok.status_code == 201, tok.text
    api = AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
        headers={"Authorization": f"Bearer {tok.json()['token']}"},
    )
    try:
        bad = []
        for m, p in (
            ("GET", f"/projects/{p2}"), ("GET", f"/projects/{p2}/entities"),
            ("GET", f"/projects/{p2}/spec"), ("POST", f"/projects/{p2}/entities"),
            ("GET", f"/projects/{p2}/search"), ("GET", f"/projects/{p2}/events/stream"),
            ("GET", f"/projects/{p2}/imports/records/export.csv"), ("GET", "/orgs"),
            ("POST", "/projects"), ("GET", "/account/tokens"),
        ):
            r = await api.request(m, p, json={"name": "x"})
            if r.status_code in (200, 201, 204) and p != "/orgs":
                bad.append(f"{m} {p} -> {r.status_code}")
        assert bad == []
        assert (await api.get(f"/projects/{p1}")).status_code == 200
        lst = (await api.get("/projects")).json()
        assert [x["id"] for x in lst["items"]] == [p1]
    finally:
        await api.aclose()


async def test_revoked_token_replay_and_scope_downgrade(client_for: ClientFor) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    a = await client_for("victim@example.com")
    p = await make_project(a, "One")
    tok = (await a.post("/account/tokens", json={"name": "r", "scopes": ["read"]})).json()
    api = AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
        headers={"Authorization": f"Bearer {tok['token']}"},
    )
    try:
        assert (await api.get(f"/projects/{p}")).status_code == 200
        assert (await api.patch(f"/projects/{p}", json={"name": "x"})).status_code == 403
        assert (await api.delete(f"/projects/{p}")).status_code == 403
        assert (await api.get(f"/projects/{p}/generate/download")).status_code == 403
        assert (await a.delete(f"/account/tokens/{tok['id']}")).status_code == 204
        assert (await api.get(f"/projects/{p}")).status_code == 401
        assert (await a.delete(f"/account/tokens/{tok['id']}")).status_code in (204, 404)
    finally:
        await api.aclose()


async def test_org_member_removed_loses_unpinned_token_reach(client_for: ClientFor) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    a = await client_for("victim@example.com")
    m = await client_for("member@example.com")
    await _team_org(a, "victimco")
    await _add_member(a, "victimco", m, "member")
    pid = await _mk(a, "victimco", "Shared")
    assert (await a.post(f"/projects/{pid}/members", json={"email": "member@example.com", "role": "editor"})).status_code in (201, 409)
    tok = (await m.post("/account/tokens", json={"name": "u", "scopes": ["write"]})).json()
    api = AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
        headers={"Authorization": f"Bearer {tok['token']}"},
    )
    try:
        assert (await api.get("/orgs/victimco")).status_code == 200
        assert (await a.delete(f"/orgs/victimco/members/{m.user.id}")).status_code == 204  # type: ignore[attr-defined]
        for p in (f"/projects/{pid}", f"/projects/{pid}/entities", "/orgs/victimco", "/orgs/victimco/members"):
            assert (await api.get(p)).status_code == 404, p
        assert "Shared" not in (await api.get("/projects")).text
    finally:
        await api.aclose()


async def test_mcp_list_projects_honours_org_require_mfa(
    client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """An org that requires MFA must not have project names listed over MCP to a member whose
    session did not satisfy MFA (every other MCP tool runs _check_org and refuses)."""
    from app.models.platform import Organization

    a, b = await two_orgs(client_for)
    await _team_org(a, "mfaco")
    await _add_member(a, "mfaco", b, "member")
    pid = await _mk(a, "mfaco", "MfaGatedProjectName")
    async with session_factory() as s:
        s.add(ProjectMember(project_id=uid(pid), user_id=b.user.id, role=MemberRole.editor, mcp_enabled=True))  # type: ignore[attr-defined]
        oid = (await a.get("/orgs/mfaco")).json()["id"]
        org = await s.get(Organization, uid(oid))
        assert org is not None
        org.require_mfa = True
        await s.commit()
    async with session_factory() as s:
        svc = McpService(s)
        principal = _principal(b.user)  # type: ignore[attr-defined]
        assert not principal.mfa_satisfied
        try:
            await svc.get_project_spec(principal, uid(pid))
            assert False, "get_project_spec ignored require_mfa"
        except AppError as exc:
            assert exc.status_code == 403
        try:
            listed = await svc.list_projects(principal)
        except AppError:
            listed = []
        assert "MfaGatedProjectName" not in str(listed), "list_projects ignores org require_mfa"
