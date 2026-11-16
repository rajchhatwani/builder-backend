"""API-key scopes and role sweeps: a read token, a viewer and a stranger walk every route of the app
with real project ids; nothing that changes state may answer 2xx."""

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_authz as authz
from app.main import app
from app.models.enums import AccountStatus
from app.models.platform import ApiToken, PlatformUser
from tests.api._auth_helpers import make_entity, make_project
from tests.api._routes import RouteInfo, all_routes
from tests.api.conftest import ClientFor, add_to_project_org

DUMMY = "00000000-0000-4000-8000-000000000009"
WRITE = ("POST", "PUT", "PATCH", "DELETE")
GATES = {"guard", "org_context", "current_principal", "session_principal", "acting_principal"}
# Read-only POSTs a viewer or a read token may call (compute an answer, change nothing).
READ_ONLY_POSTS = {t for m, t in authz._READ_ONLY_POSTS}


def _fill(path: str, ids: dict[str, str]) -> str:
    for k, v in ids.items():
        path = path.replace("{" + k + "}", v)
    path = path.replace("{domain}", "evil.example").replace("{metric}", "projects")
    return re.sub(r"{[^}]+}", DUMMY, path)


def _gated(r: RouteInfo) -> bool:
    return bool(r.names & GATES)


def _api(token: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _token(c: AsyncClient, **body: object) -> str:
    r = await c.post("/account/tokens", json={"name": "t", "scopes": ["read"], **body})
    assert r.status_code == 201, r.text
    return str(r.json()["token"])


async def _world(client_for: ClientFor) -> tuple[AsyncClient, str, str]:
    a = await client_for("owner@example.com")
    pid = await make_project(a, "One")
    await make_entity(a, pid, "Thing")
    return a, pid, (await a.get("/orgs")).json()["items"][0]["slug"]


async def _sweep(
    client: AsyncClient,
    ids: dict[str, str],
    methods: tuple[str, ...],
    skip_read_only: bool = True,
    only_project: bool = False,
) -> list[str]:
    bad: list[str] = []
    last: list[RouteInfo] = []
    for r in all_routes():
        if r.method not in methods or not _gated(r):
            continue
        if skip_read_only and r.path in READ_ONLY_POSTS:
            continue
        if only_project and r.path.startswith(("/account", "/orgs", "/admin")):
            continue  # self-service and org routes are not what a project role guards
        # destructive project routes last so one wrongly open route cannot hide the rest
        if r.method == "DELETE" and r.path in ("/projects/{project_id}", "/orgs/{slug}"):
            last.append(r)
            continue
        resp = await client.request(r.method, _fill(r.path, ids), json={})
        if resp.status_code < 400 or resp.status_code >= 500:
            bad.append(f"{r.method} {r.path} -> {resp.status_code}")
    for r in last:
        resp = await client.request(r.method, _fill(r.path, ids), json={})
        if resp.status_code < 400 or resp.status_code >= 500:
            bad.append(f"{r.method} {r.path} -> {resp.status_code}")
    return bad


async def test_read_token_cannot_write_anywhere(client_for: ClientFor) -> None:
    a, pid, slug = await _world(client_for)
    api = _api(await _token(a))
    try:
        bad = await _sweep(api, {"project_id": pid, "slug": slug}, WRITE)
    finally:
        await api.aclose()
    # 5xx would mean the handler ran with a body it could not take; 2xx/3xx means the scope was ignored
    assert bad == []
    assert (await a.get(f"/projects/{pid}")).status_code == 200, "the project must have survived"


async def test_pinned_write_token_cannot_create_or_join_orgs(client_for: ClientFor) -> None:
    a, pid, _ = await _world(client_for)
    b = await client_for("joiner@example.com")
    bpid = await make_project(b, "Mine")
    assert (await a.post("/orgs", json={"name": "Team", "slug": "teamorg"})).status_code == 201
    inv = await a.post("/orgs/teamorg/invitations", json={"email": b.user.email, "role": "member"})  # type: ignore[attr-defined]
    assert inv.status_code == 201, inv.text
    api = _api(await _token(a, scopes=["write"], project_id=pid))
    bapi = _api(await _token(b, scopes=["write"], project_id=bpid))
    try:
        made = await api.post("/orgs", json={"name": "Side", "slug": "sideorg"})
        joined = await bapi.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    finally:
        await api.aclose()
        await bapi.aclose()
    bad = {k: v.status_code for k, v in {"create org": made, "accept invitation": joined}.items() if v.status_code != 403}
    assert bad == {}, f"a project-pinned token reached org-level writes: {bad}"
    assert "sideorg" not in [o["slug"] for o in (await a.get("/orgs")).json()["items"]]
    members = (await a.get("/orgs/teamorg/members")).json()
    assert b.user.email not in str(members), "the pinned token joined the org"  # type: ignore[attr-defined]


async def test_pinned_token_cannot_list_orgs_or_pending_invitations(client_for: ClientFor) -> None:
    a, pid, _ = await _world(client_for)
    api = _api(await _token(a, scopes=["write"], project_id=pid))
    try:
        orgs = await api.get("/orgs")
        pending = await api.get("/orgs/invitations/pending")
    finally:
        await api.aclose()
    assert orgs.status_code in (403, 404) or orgs.json()["items"] == [], "org list leaked to a pinned token"
    assert pending.status_code in (403, 404) or pending.json()["items"] == []


async def test_viewer_cannot_change_anything(client_for: ClientFor) -> None:
    a, pid, slug = await _world(client_for)
    v = await client_for("viewer@example.com")
    await add_to_project_org(pid, v.user.email)  # type: ignore[attr-defined]
    r = await a.post(f"/projects/{pid}/members", json={"email": v.user.email, "role": "viewer"})  # type: ignore[attr-defined]
    assert r.status_code == 201, r.text
    bad = await _sweep(v, {"project_id": pid, "slug": slug}, WRITE, only_project=True)
    assert bad == []
    assert (await a.get(f"/projects/{pid}")).status_code == 200


async def test_viewer_write_token_is_still_a_viewer(client_for: ClientFor) -> None:
    a, pid, slug = await _world(client_for)
    v = await client_for("viewer@example.com")
    await add_to_project_org(pid, v.user.email)  # type: ignore[attr-defined]
    await a.post(f"/projects/{pid}/members", json={"email": v.user.email, "role": "viewer"})  # type: ignore[attr-defined]
    api = _api(await _token(v, scopes=["write", "generate"]))
    try:
        bad = await _sweep(api, {"project_id": pid, "slug": slug}, WRITE, only_project=True)
    finally:
        await api.aclose()
    assert bad == []


async def test_stranger_gets_nothing_from_any_project_route(client_for: ClientFor) -> None:
    a, pid, _ = await _world(client_for)
    x = await client_for("stranger@example.com")
    leaks: list[str] = []
    for r in all_routes():
        if "{project_id}" not in r.path or not _gated(r) or r.path.startswith("/orgs/"):
            continue
        if r.method == "DELETE" and r.path == "/projects/{project_id}":
            continue
        resp = await x.request(r.method, _fill(r.path, {"project_id": pid}), json={} if r.method != "GET" else None)
        if resp.status_code != 404:
            leaks.append(f"{r.method} {r.path} -> {resp.status_code}")
    assert leaks == []
    assert (await x.delete(f"/projects/{pid}")).status_code == 404
    assert (await a.get(f"/projects/{pid}")).status_code == 200


async def test_head_probe_by_a_stranger_reveals_nothing(client_for: ClientFor) -> None:
    a, pid, _ = await _world(client_for)
    x = await client_for("stranger@example.com")
    real = await x.head(f"/projects/{pid}")
    fake = await x.head(f"/projects/{uuid.uuid4()}")
    assert real.status_code == fake.status_code, (real.status_code, fake.status_code)
    assert real.status_code != 200


async def test_mangled_token_forms_are_refused(client_for: ClientFor) -> None:
    a, pid, _ = await _world(client_for)
    tok = await _token(a)
    bad: list[str] = []
    for label, header in {
        "extra char": f"Bearer {tok}x",
        "truncated": f"Bearer {tok[:-1]}",
        "upper prefix": f"Bearer {tok.replace('bb_pat_', 'BB_PAT_', 1)}",
        "basic scheme": f"Basic {tok}",
        "token scheme": f"Token {tok}",
        "empty": "Bearer ",
        "two tokens": f"Bearer {tok} {tok}",
        "nul": f"Bearer {tok}\x00",
    }.items():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            try:
                r = await c.get(f"/projects/{pid}", headers={"Authorization": header})
            except Exception:  # noqa: BLE001 - an illegal header is refused before the app
                continue
        if r.status_code == 200:
            bad.append(label)
    assert bad == []


async def test_expired_and_suspended_owner_tokens_stop_working(
    client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, pid, _ = await _world(client_for)
    t1 = await _token(a)
    t2 = await _token(a)
    api1, api2 = _api(t1), _api(t2)
    try:
        assert (await api1.get(f"/projects/{pid}")).status_code == 200
        async with session_factory() as s:
            tokens = (await s.execute(ApiToken.__table__.select())).all()
            assert len(tokens) == 2
            first = sorted(tokens, key=lambda r: r.created_at)[0]
            await s.execute(update(ApiToken).where(ApiToken.id == first.id).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
            await s.commit()
        assert (await api1.get(f"/projects/{pid}")).status_code == 401
        assert (await api2.get(f"/projects/{pid}")).status_code == 200
        async with session_factory() as s:
            await s.execute(update(PlatformUser).where(PlatformUser.id == a.user.id).values(status=AccountStatus.suspended))  # type: ignore[attr-defined]
            await s.commit()
        assert (await api2.get(f"/projects/{pid}")).status_code == 401
    finally:
        await api1.aclose()
        await api2.aclose()


async def test_token_loses_write_when_its_owner_is_demoted(client_for: ClientFor) -> None:
    a, pid, _ = await _world(client_for)
    e = await client_for("editor@example.com")
    await add_to_project_org(pid, e.user.email)  # type: ignore[attr-defined]
    await a.post(f"/projects/{pid}/members", json={"email": e.user.email, "role": "editor"})  # type: ignore[attr-defined]
    api = _api(await _token(e, scopes=["write"], project_id=pid))
    try:
        assert (await api.post(f"/projects/{pid}/entities", json={"name": "Before"})).status_code == 201
        r = await a.patch(f"/projects/{pid}/members/{e.user.id}", json={"role": "viewer"})  # type: ignore[attr-defined]
        assert r.status_code == 200, r.text
        assert (await api.post(f"/projects/{pid}/entities", json={"name": "After"})).status_code == 403
        r = await a.delete(f"/projects/{pid}/members/{e.user.id}")  # type: ignore[attr-defined]
        assert r.status_code == 204
        assert (await api.get(f"/projects/{pid}")).status_code == 404
    finally:
        await api.aclose()


async def test_token_cannot_mint_tokens_or_change_the_account(client_for: ClientFor) -> None:
    a, pid, _ = await _world(client_for)
    api = _api(await _token(a, scopes=["write", "generate"]))
    try:
        codes = {
            "mint": (await api.post("/account/tokens", json={"name": "n", "scopes": ["write"]})).status_code,
            "list": (await api.get("/account/tokens")).status_code,
            "pw": (await api.post("/account/password", json={"current_password": "x", "new_password": "y" * 12})).status_code,
            "delete": (await api.delete("/account")).status_code,
        }
    finally:
        await api.aclose()
    assert all(c in (401, 403, 404, 405, 422) for c in codes.values()), codes


async def test_parallel_use_of_one_token_after_revoke_is_refused(client_for: ClientFor) -> None:
    a, pid, _ = await _world(client_for)
    r = await a.post("/account/tokens", json={"name": "t", "scopes": ["read"]})
    tid, tok = r.json()["id"], r.json()["token"]
    api = _api(tok)
    try:
        assert (await a.delete(f"/account/tokens/{tid}")).status_code == 204
        codes = await asyncio.gather(*(api.get(f"/projects/{pid}") for _ in range(8)))
    finally:
        await api.aclose()
    assert {c.status_code for c in codes} == {401}


@pytest.mark.parametrize(
    "scopes",
    [["read", "read"], ["READ"], [], ["read\x00"], ["mcp:read", "bogus"], ["*"], ["write "]],
)
async def test_odd_scope_lists_never_create_a_wider_token(client_for: ClientFor, scopes: list[str]) -> None:
    a, pid, _ = await _world(client_for)
    r = await a.post("/account/tokens", json={"name": "t", "scopes": scopes})
    if r.status_code == 201:
        granted = set(r.json()["scopes"])
        assert granted <= set(scopes) and granted <= authz.VALID_SCOPES, granted
    else:
        assert r.status_code in (400, 422), r.status_code
