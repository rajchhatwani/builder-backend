"""Org-scoped attacks: other org's slug, role escalation across two orgs, project join/transfer,
invitations, default-org switching, audit/export reads, concurrency."""

import asyncio
import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import platform_authz as authz
from app.models.platform import AuditLog
from app.models.project import Project
from app.models.enums import OrgRole
from tests.api._auth_helpers import make_entity, make_project
from tests.api._routes import all_routes
from tests.api.conftest import ClientFor
from tests.audit.tenant_rls._world import uid

DUMMY = "00000000-0000-4000-8000-000000000009"


def _org_paths(slug: str) -> list[tuple[str, str]]:
    out = []
    for r in all_routes():
        if not r.path.startswith("/orgs/{slug}"):
            continue
        p = r.path.replace("{slug}", slug)
        p = re.sub(r"{domain}", "evil.example", p)
        p = re.sub(r"{metric}", "projects", p)
        p = re.sub(r"{[^}]+}", DUMMY, p)
        out.append((r.method, p))
    return out


async def _team_org(c: AsyncClient, slug: str) -> None:
    r = await c.post("/orgs", json={"name": slug.title(), "slug": slug})
    assert r.status_code == 201, r.text


async def _mk(c: AsyncClient, slug: str, name: str) -> str:
    oid = (await c.get(f"/orgs/{slug}")).json()["id"]
    r = await c.post("/projects", json={"name": name, "organization_id": oid})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _add_member(owner: AsyncClient, slug: str, who: AsyncClient, role: str) -> None:
    inv = await owner.post(f"/orgs/{slug}/invitations", json={"email": who.user.email, "role": role})  # type: ignore[attr-defined]
    assert inv.status_code == 201, inv.text
    acc = await who.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    assert acc.status_code == 200, acc.text


async def test_stranger_gets_404_on_every_org_route(client_for: ClientFor) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    await _team_org(a, "victimco")
    bad = []
    for method, path in _org_paths("victimco"):
        r = await b.request(method, path, json={})
        if r.status_code != 404:
            bad.append(f"{method} {path} -> {r.status_code}")
    assert bad == [], "\n".join(bad)


async def test_plain_member_is_refused_everything_above_member(client_for: ClientFor) -> None:
    a = await client_for("victim@example.com")
    m = await client_for("member@example.com")
    await _team_org(a, "victimco")
    await _add_member(a, "victimco", m, "member")
    bad = []
    for method, tpl in [(r.method, r.path) for r in all_routes() if r.path.startswith("/orgs/{slug}")]:
        needed = authz.required_org_role(method, tpl)
        if needed is None or needed is OrgRole.member:
            continue
        p = tpl.replace("{slug}", "victimco")
        p = p.replace("{domain}", "evil.example").replace("{metric}", "projects")
        p = re.sub(r"{[^}]+}", DUMMY, p)
        r = await m.request(method, p, json={})
        if r.status_code != 403:
            bad.append(f"{method} {tpl} (needs {needed.value}) -> {r.status_code}")
    assert bad == [], "\n".join(bad)


async def test_member_of_two_orgs_has_no_role_crossover(client_for: ClientFor) -> None:
    """owner in org B, plain member in org A: B-owner rights must not apply to A."""
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    await _team_org(a, "victimco")
    await _team_org(b, "attackco")
    await _add_member(a, "victimco", b, "member")
    assert (await b.patch("/orgs/attackco", json={"name": "Mine"})).status_code == 200
    assert (await b.patch("/orgs/victimco", json={"name": "Hijacked"})).status_code == 403
    assert (await b.get("/orgs/victimco/export")).status_code == 403
    assert (await b.get("/orgs/victimco/audit")).status_code == 403
    assert (await b.delete("/orgs/victimco")).status_code == 403
    assert (await a.get("/orgs/victimco")).json()["name"] == "Victimco"


async def test_project_transfer_and_join_with_a_foreign_project_id(
    client_for: ClientFor, session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    await _team_org(a, "victimco")
    await _team_org(b, "attackco")
    pid = await _mk(a, "victimco", "V")
    for path, body in (
        (f"/orgs/attackco/projects/{pid}/transfer", {"to_slug": "attackco"}),
        (f"/orgs/attackco/projects/{pid}/join", {"role": "owner"}),
        (f"/orgs/victimco/projects/{pid}/transfer", {"to_slug": "attackco"}),
        (f"/orgs/victimco/projects/{pid}/join", {"role": "owner"}),
    ):
        r = await b.post(path, json=body)
        assert r.status_code in (403, 404), f"{path} -> {r.status_code} {r.text[:80]}"
    async with session_factory() as s:
        proj = await s.get(Project, uid(pid))
        assert proj is not None
        org_a = (await a.get("/orgs/victimco")).json()["id"]
        assert str(proj.organization_id) == org_a
    assert (await b.get(f"/projects/{pid}")).status_code == 404


async def test_owner_cannot_transfer_project_into_an_org_they_only_belong_to(
    client_for: ClientFor,
) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    await _team_org(a, "victimco")
    await _team_org(b, "attackco")
    await _add_member(a, "victimco", b, "admin")
    pb = await _mk(b, "attackco", "Mine")
    r = await b.post(f"/orgs/attackco/projects/{pb}/transfer", json={"to_slug": "victimco"})
    assert r.status_code in (403, 409), r.text  # admin in destination, not owner
    r2 = await b.post(f"/orgs/attackco/projects/{pb}/transfer", json={"to_slug": "no-such-org"})
    assert r2.status_code == 404


async def test_invitation_ids_and_tokens_of_another_org(client_for: ClientFor) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    c = await client_for("invitee@example.com")
    await _team_org(a, "victimco")
    await _team_org(b, "attackco")
    inv = (
        await a.post("/orgs/victimco/invitations", json={"email": "invitee@example.com", "role": "admin"})
    ).json()
    # B names A's invitation under B's own slug
    assert (await b.delete(f"/orgs/attackco/invitations/{inv['id']}")).status_code == 404
    assert (await b.post(f"/orgs/attackco/invitations/{inv['id']}/resend")).status_code == 404
    # B (not the invitee) accepts by id, and by stolen token
    assert (await b.post(f"/orgs/invitations/{inv['id']}/accept")).status_code in (403, 404)
    stolen = await b.post("/orgs/invitations/accept", json={"token": inv["token"]})
    assert stolen.status_code in (403, 404), stolen.text
    assert (await b.get("/orgs/victimco")).status_code == 404
    # the real invitee still can
    assert (await c.post("/orgs/invitations/accept", json={"token": inv["token"]})).status_code == 200


async def test_default_organization_cannot_be_set_to_a_foreign_org(client_for: ClientFor) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    await _team_org(a, "victimco")
    foreign = (await a.get("/orgs/victimco")).json()["id"]
    for ident in (foreign, "victimco"):
        for key in ("organization_id", "slug", "organization_slug"):
            r = await b.put("/account/me/default-organization", json={key: ident})
            assert r.status_code in (404, 422), f"{key}={ident} -> {r.status_code}"
    me = (await b.get("/account/me")).json()
    assert foreign not in str(me)


async def test_removed_member_loses_project_and_token_access(client_for: ClientFor) -> None:
    a = await client_for("victim@example.com")
    m = await client_for("member@example.com")
    await _team_org(a, "victimco")
    await _add_member(a, "victimco", m, "member")
    pid = await _mk(a, "victimco", "Shared")
    assert (await a.post(f"/projects/{pid}/members", json={"email": "member@example.com", "role": "editor"})).status_code == 201
    assert (await m.get(f"/projects/{pid}")).status_code == 200
    tok = await m.post("/account/tokens", json={"name": "ci", "scopes": ["write"], "project_id": pid})
    assert tok.status_code == 201, tok.text
    raw = tok.json()["token"]
    api = AsyncClient(transport=m._transport, base_url="http://testserver", headers={"Authorization": f"Bearer {raw}"})  # type: ignore[attr-defined]
    assert (await api.get(f"/projects/{pid}")).status_code == 200
    removed = await a.delete(f"/orgs/victimco/members/{m.user.id}")  # type: ignore[attr-defined]
    assert removed.status_code == 204, removed.text
    assert (await m.get(f"/projects/{pid}")).status_code == 404
    assert (await api.get(f"/projects/{pid}")).status_code == 404
    assert (await api.get(f"/projects/{pid}/entities")).status_code == 404
    assert (await m.get("/orgs/victimco")).status_code == 404
    await api.aclose()


async def test_audit_and_export_show_only_own_org(
    client_for: ClientFor, session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    await _team_org(a, "victimco")
    await _team_org(b, "attackco")
    pa = await _mk(a, "victimco", "VSecretName")
    await make_entity(a, pa, "VSecretEntity")
    await _add_member(a, "victimco", await client_for("x@example.com"), "member")
    audit = await b.get("/orgs/attackco/audit")
    assert audit.status_code == 200
    assert "victim" not in audit.text.lower() and pa not in audit.text
    exp = await b.get("/orgs/attackco/export")
    assert exp.status_code == 200
    blob = exp.content.decode("latin-1", "ignore")
    assert "VSecretName" not in blob and "VSecretEntity" not in blob and "victim@example.com" not in blob
    assert pa not in blob


async def test_parallel_cross_tenant_reads_all_404(client_for: ClientFor) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    pa = await make_project(a, "V")
    results = await asyncio.gather(
        *[
            b.request(m, p, json={})
            for m, p in [
                ("GET", f"/projects/{pa}"), ("GET", f"/projects/{pa}/spec"),
                ("PATCH", f"/projects/{pa}"), ("DELETE", f"/projects/{pa}"),
                ("GET", f"/projects/{pa}/entities"), ("GET", f"/projects/{pa}/search"),
                ("POST", f"/projects/{pa}/search/reindex"), ("GET", f"/projects/{pa}/presence"),
            ]
        ]
    )
    assert [r.status_code for r in results] == [404] * 8
    assert (await a.get(f"/projects/{pa}")).status_code == 200


async def test_parallel_project_creation_by_two_orgs_stays_separated(client_for: ClientFor) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    rs = await asyncio.gather(
        *[a.post("/projects", json={"name": f"A{i}"}) for i in range(4)],
        *[b.post("/projects", json={"name": f"B{i}"}) for i in range(4)],
    )
    assert all(r.status_code == 201 for r in rs), [r.text for r in rs if r.status_code != 201]
    la = {p["name"] for p in (await a.get("/projects")).json()["items"]}
    lb = {p["name"] for p in (await b.get("/projects")).json()["items"]}
    assert la == {f"A{i}" for i in range(4)} and lb == {f"B{i}" for i in range(4)}


async def test_project_cannot_be_created_inside_a_foreign_org(client_for: ClientFor) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    await _team_org(a, "victimco")
    foreign = (await a.get("/orgs/victimco")).json()["id"]
    r = await b.post("/projects", json={"name": "Planted", "organization_id": foreign})
    assert r.status_code in (403, 404), r.text
    assert (await a.get("/orgs/victimco/projects")).json()["total"] == 0
    r = await b.post("/projects", json={"name": "Planted", "organization_id": str(uuid.uuid4())})
    assert r.status_code in (403, 404)
