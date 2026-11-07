"""B3-10: preview API without Docker. The sandbox stack is replaced by a fake launcher and a tiny
local HTTP upstream; the real runsc stack is covered by tests/e2e/test_preview_stack.py."""

import asyncio
import json
import os
import uuid
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.core import platform_security as sec
from app.main import app
from app.models.enums import PlatformRole
from app.models.platform import AuditLog
from app.models.preview import Preview
from app.models.project import Project
from app.services import preview_runtime as rt
from app.services import preview_service as ps
from app.services.sandbox import ReapResult
from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor, add_to_project_org

TOKEN = "X-Preview-Token"


class FakeBox:
    def __init__(self) -> None:
        self.alive = True
        self.log_text = "boot ok\nDATABASE_URL=postgresql://app:hunter2pw@db/app\nSECRET_KEY=abc123xyz\n"

    async def is_running(self, _sid: str) -> bool:
        return self.alive

    async def logs(self, _sid: str, tail: int = 2000, since: str | None = None) -> str:
        return self.log_text if since is None else ""


async def _upstream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    method, target, _ = lines[0].split(" ")
    headers = {k.lower(): v for k, v in (ln.split(": ", 1) for ln in lines[1:] if ": " in ln)}
    n = int(headers.get("content-length", "0"))
    body = await reader.readexactly(n) if n else b""
    payload = json.dumps(
        {"method": method, "target": target, "headers": headers, "body": body.decode()}
    ).encode()
    ctype = b"image/svg+xml" if target.startswith("/svg") else b"application/json"
    writer.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: " + ctype + b"\r\nSet-Cookie: evil=1\r\n"
        b"Location: https://evil.example/x\r\nAccess-Control-Allow-Origin: *\r\n"
        b"Access-Control-Allow-Credentials: true\r\nLink: <https://evil.example>; rel=preload\r\n"
        b"Refresh: 0; url=https://evil.example\r\n"
        b"Server: upstream\r\nContent-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload
    )
    await writer.drain()
    writer.close()


@pytest.fixture
async def stack(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
) -> AsyncIterator[dict[str, object]]:
    settings = Settings(
        environment="test",
        preview_root=str(tmp_path / "pv"),
        preview_wake_timeout_seconds=10,
        preview_max_body_bytes=2048,
        preview_log_stream_max_seconds=2,
        preview_lazy_sweep=False,
    )
    server = await asyncio.start_server(_upstream, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(rt, "APP_PORT", port)
    box = FakeBox()
    state: dict[str, object] = {"launches": [], "teardowns": [], "box": box, "settings": settings}

    async def fake_launch(_box: object, spec: rt.StackSpec, _settings: Settings) -> str:
        state["launches"].append(spec)  # type: ignore[attr-defined]
        box.alive = True
        return "127.0.0.1"

    async def fake_teardown(_box: object, db: str, app_: str) -> None:
        state["teardowns"].append((db, app_))  # type: ignore[attr-defined]

    async def fake_reap(_s: Settings | None = None) -> ReapResult:
        return ReapResult()

    monkeypatch.setattr(rt, "launch", fake_launch)
    monkeypatch.setattr(rt, "teardown", fake_teardown)
    monkeypatch.setattr(ps, "get_settings", lambda: settings)
    monkeypatch.setattr(ps, "get_sandbox", lambda s=None: box)
    monkeypatch.setattr(ps, "reap_expired", fake_reap)
    monkeypatch.setattr(ps, "session_factory", lambda: session_factory)
    from app.api import previews as api

    monkeypatch.setattr(api, "get_settings", lambda: settings)
    api._windows.clear()
    ps._last_touch.clear()
    ps._last_lazy = 0.0
    api._open_streams.clear()
    yield state
    server.close()
    await server.wait_closed()
    for t in list(ps._tasks):
        await asyncio.gather(t, return_exceptions=True)


async def _create(c: AsyncClient, pid: str, **body: object) -> dict[str, object]:
    r = await c.post(f"/projects/{pid}/previews", json=body)
    assert r.status_code == 201, r.text
    out: dict[str, object] = r.json()
    return out


async def _wait_state(c: AsyncClient, pid: str, prev: str, want: str) -> dict[str, object]:
    for _ in range(60):
        r = await c.get(f"/projects/{pid}/previews/{prev}")
        if r.json()["state"] == want:
            out: dict[str, object] = r.json()
            return out
        await asyncio.sleep(0.1)
    raise AssertionError(f"preview never became {want}: {r.text}")


async def _project_with_entity(c: AsyncClient) -> str:
    pid = await make_project(c)
    await make_entity(c, pid)
    return pid


@pytest.fixture
async def anon(override_session: None) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def test_unconfigured_previews_answer_503(client: AsyncClient) -> None:
    pid = await make_project(client)
    assert (await client.post(f"/projects/{pid}/previews", json={})).status_code == 503


async def test_create_returns_token_once_and_stores_only_a_hash(
    client: AsyncClient, stack: dict[str, object], session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    pid = await _project_with_entity(client)
    created = await _create(client, pid)
    token = str(created["token"])
    assert created["state"] == "starting" and created["is_preview"] is True
    assert created["url_path"] == f"/previews/{created['id']}/"
    done = await _wait_state(client, pid, str(created["id"]), "running")
    assert "token" not in done
    assert token not in (await client.get(f"/projects/{pid}/previews")).text
    async with session_factory() as s:
        row = await s.get(Preview, uuid.UUID(str(created["id"])))
        assert row is not None and row.token_hash != token and token not in str(row.token_hash)
        assert (Path(row.code_dir or "") / "app" / "main.py").exists()  # generated code is on disk
        assert row.limits["memory_mb"] == 512
    # the audit log records the creation, without the token
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(AuditLog.action == "preview.create"))).scalars().all()
        assert len(rows) == 1 and token not in json.dumps(rows[0].detail or {})


async def test_proxy_requires_the_token_and_marks_responses(
    client: AsyncClient, anon: AsyncClient, stack: dict[str, object]
) -> None:
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    base = f"/previews/{c['id']}"
    for headers in ({}, {TOKEN: "bbp_wrong"}, {TOKEN: ""}):
        r = await anon.get(f"{base}/items", headers=headers)
        assert r.status_code == 401, headers
    unknown = await anon.get(f"/previews/{uuid.uuid4()}/items", headers={TOKEN: str(c["token"])})
    assert unknown.status_code == 401  # same answer as a wrong token
    r = await anon.post(
        f"{base}/items?x=1",
        headers={TOKEN: str(c["token"]), "Cookie": "bb_refresh=platform-secret", "X-Custom": "yes"},
        content=b'{"a":1}',
    )
    assert r.status_code == 200, r.text
    seen = r.json()
    assert seen["target"] == "/items?x=1" and seen["body"] == '{"a":1}'
    assert seen["headers"].get("x-custom") == "yes"
    assert "cookie" not in seen["headers"] and TOKEN.lower() not in seen["headers"]
    assert r.headers["x-preview"] == "true" and r.headers["x-preview-id"] == c["id"]
    assert "set-cookie" not in r.headers and "x-robots-tag" in r.headers
    assert (await anon.get(base, headers={TOKEN: str(c["token"])})).json()["target"] == "/"
    # request body cap
    big = await anon.post(f"{base}/items", headers={TOKEN: str(c["token"])}, content=b"x" * 4096)
    assert big.status_code == 413


async def test_rate_cap_returns_429_with_retry_after(
    client: AsyncClient, anon: AsyncClient, stack: dict[str, object], session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    async with session_factory() as s:
        row = await s.get(Preview, uuid.UUID(str(c["id"])))
        assert row is not None
        row.limits = {**row.limits, "rate_per_minute": 3}
        await s.commit()
    h = {TOKEN: str(c["token"])}
    codes = [(await anon.get(f"/previews/{c['id']}/x", headers=h)).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    r = await anon.get(f"/previews/{c['id']}/x", headers=h)
    assert int(r.headers["retry-after"]) >= 1


async def test_sleep_wake_and_expiry_sweep(
    client: AsyncClient, anon: AsyncClient, stack: dict[str, object], session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    h = {TOKEN: str(c["token"])}
    # idle for longer than sleep_after_minutes -> sleeping, stack torn down
    res = await ps.sweep(now=datetime.now(UTC) + timedelta(minutes=45))
    assert res.slept == 1
    assert (await client.get(f"/projects/{pid}/previews/{c['id']}")).json()["state"] == "sleeping"
    assert len(stack["teardowns"]) == 1  # type: ignore[arg-type]
    # the next request wakes it (a second launch) and is answered
    r = await anon.get(f"/previews/{c['id']}/items", headers=h)
    assert r.status_code == 200
    assert len(stack["launches"]) == 2  # type: ignore[arg-type]
    row = (await client.get(f"/projects/{pid}/previews/{c['id']}")).json()
    assert row["state"] == "running"
    # a container that died is noticed and rebuilt on the next request
    stack["box"].alive = False  # type: ignore[attr-defined]
    assert (await ps.sweep()).healed == 1
    assert (await anon.get(f"/previews/{c['id']}/items", headers=h)).status_code == 200
    # expiry: stack gone, code wiped, token dead
    code_dir = Path(str(stack["settings"].preview_root)) / uuid.UUID(str(c["id"])).hex  # type: ignore[attr-defined]
    assert code_dir.exists()
    async with session_factory() as s:
        await s.execute(
            update(Preview).where(Preview.id == uuid.UUID(str(c["id"]))).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert (await ps.sweep()).expired == 1
    assert not code_dir.exists()
    assert (await client.get(f"/projects/{pid}/previews/{c['id']}")).json()["state"] == "expired"
    assert (await anon.get(f"/previews/{c['id']}/items", headers=h)).status_code == 401
    assert (await ps.sweep()).expired == 0  # idempotent


async def test_quota_and_per_org_override(
    client: AsyncClient, stack: dict[str, object], client_for: ClientFor, session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    pid = await _project_with_entity(client)
    for _ in range(3):
        await _create(client, pid)
    r = await client.post(f"/projects/{pid}/previews", json={})
    assert r.status_code == 409 and r.json()["code"] == "preview_quota"
    # an admin raises this org's limit; a kill frees a slot too
    admin = await client_for("root@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN)
    async with session_factory() as s:
        org_id = (await s.get(Project, uuid.UUID(pid))).organization_id  # type: ignore[union-attr]
    put = await admin.put(
        f"/admin/preview-limits/orgs/{org_id}",
        json={"overrides": {"max_live_per_user": 4}, "note": "pilot", "allow_above_default": True},
    )
    assert put.status_code == 200, put.text
    assert put.json()["effective"]["max_live_per_user"] == 4
    await _create(client, pid)
    assert (await client.post(f"/projects/{pid}/previews", json={})).status_code == 409


async def test_kill_switch_blocks_creation_proxy_and_kills_live_previews(
    client: AsyncClient, anon: AsyncClient, stack: dict[str, object], client_for: ClientFor
) -> None:
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    admin = await client_for("root@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN)
    r = await admin.put("/admin/preview-limits", json={"kill_switch": True})
    assert r.status_code == 200 and r.json()["kill_switch"] is True
    blocked = await client.post(f"/projects/{pid}/previews", json={})
    assert blocked.status_code == 503 and blocked.json()["code"] == "previews_disabled"
    h = {TOKEN: str(c["token"])}
    await asyncio.gather(*list(ps._tasks))  # the immediate sweep started by the toggle
    # killed and wiped: the token is dead (and a still-live one would get 503, see the log test)
    assert (await anon.get(f"/previews/{c['id']}/x", headers=h)).status_code == 401
    assert (await ps.sweep()).killed == 0
    assert (await client.get(f"/projects/{pid}/previews/{c['id']}")).json()["state"] == "killed"
    await admin.put("/admin/preview-limits", json={"kill_switch": False})
    await _create(client, pid)  # back to normal


async def test_org_can_be_switched_off(
    client: AsyncClient, stack: dict[str, object], client_for: ClientFor, session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    pid = await _project_with_entity(client)
    admin = await client_for("root@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN)
    async with session_factory() as s:
        org_id = (await s.get(Project, uuid.UUID(pid))).organization_id  # type: ignore[union-attr]
    await admin.put(f"/admin/preview-limits/orgs/{org_id}", json={"enabled": False})
    assert (await client.post(f"/projects/{pid}/previews", json={})).status_code == 503
    assert (await admin.delete(f"/admin/preview-limits/orgs/{org_id}")).json()["enabled"] is True
    await _create(client, pid)


async def test_unverified_email_cannot_create(client_for: ClientFor, stack: dict[str, object]) -> None:
    c = await client_for("unverified@example.com", email_verified_at=None)
    pid = await _project_with_entity(c)
    r = await c.post(f"/projects/{pid}/previews", json={})
    assert r.status_code == 403 and r.json()["code"] == "email_not_verified"
    assert (await c.get(f"/projects/{pid}/generate/self-host-kit")).status_code == 403


async def test_roles_and_idor(
    client: AsyncClient, anon: AsyncClient, stack: dict[str, object], client_for: ClientFor
) -> None:
    pid = await _project_with_entity(client)
    other_pid = await _project_with_entity(client)
    c = await _create(client, pid)
    prev = c["id"]
    viewer = await client_for("viewer@example.com")
    outsider = await client_for("outsider@example.com")
    await add_to_project_org(pid, "viewer@example.com")
    r = await client.post(f"/projects/{pid}/members", json={"email": "viewer@example.com", "role": "viewer"})
    assert r.status_code == 201, r.text
    # viewers may look but not create, kill or rotate; they never see the token
    assert (await viewer.get(f"/projects/{pid}/previews")).status_code == 200
    got = await viewer.get(f"/projects/{pid}/previews/{prev}")
    assert got.status_code == 200 and c["token"] not in got.text
    assert (await viewer.post(f"/projects/{pid}/previews", json={})).status_code == 403
    assert (await viewer.delete(f"/projects/{pid}/previews/{prev}")).status_code == 403
    assert (await viewer.post(f"/projects/{pid}/previews/{prev}/rotate-token")).status_code == 403
    # a viewer who has the token can open the preview
    assert (await anon.get(f"/previews/{prev}/x", headers={TOKEN: str(c["token"])})).status_code == 200
    # non-members and cross-project ids look like "not found"
    for m, path in (
        ("GET", f"/projects/{pid}/previews"),
        ("GET", f"/projects/{pid}/previews/{prev}"),
        ("POST", f"/projects/{pid}/previews"),
        ("DELETE", f"/projects/{pid}/previews/{prev}"),
        ("POST", f"/projects/{pid}/previews/{prev}/rotate-token"),
        ("GET", f"/projects/{pid}/generate/self-host-kit"),
    ):
        assert (await outsider.request(m, path, json={})).status_code == 404, (m, path)
    assert (await client.get(f"/projects/{other_pid}/previews/{prev}")).status_code == 404
    assert (await client.delete(f"/projects/{other_pid}/previews/{prev}")).status_code == 404
    # rotating invalidates the old token
    rot = await client.post(f"/projects/{pid}/previews/{prev}/rotate-token")
    assert rot.status_code == 200 and rot.json()["token"] != c["token"]
    assert (await anon.get(f"/previews/{prev}/x", headers={TOKEN: str(c["token"])})).status_code == 401
    assert (await anon.get(f"/previews/{prev}/x", headers={TOKEN: rot.json()["token"]})).status_code == 200
    # an editor kills it; the token stops working at once
    assert (await client.delete(f"/projects/{pid}/previews/{prev}")).json()["state"] == "killed"
    assert (await anon.get(f"/previews/{prev}/x", headers={TOKEN: rot.json()["token"]})).status_code == 401


async def test_log_stream_needs_the_token_and_redacts(
    client: AsyncClient, anon: AsyncClient, stack: dict[str, object]
) -> None:
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    url = f"/previews/{c['id']}/-/logs"
    assert (await anon.get(url)).status_code == 401
    r = await anon.get(url, headers={TOKEN: str(c["token"])})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert "boot ok" in r.text and "event: end" in r.text
    assert "hunter2pw" not in r.text and "abc123xyz" not in r.text
    assert r.headers["x-preview"] == "true"


async def test_admin_limits_endpoints(client_for: ClientFor, session_factory: async_sessionmaker) -> None:  # type: ignore[type-arg]
    admin = await client_for("root@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN)
    support = await client_for("help@example.com", PlatformRole.platform_support, audience=sec.AUDIENCE_ADMIN)
    customer = await client_for("cust@example.com")
    r = await admin.get("/admin/preview-limits")
    assert r.status_code == 200
    body = r.json()
    assert body["kill_switch"] is False and body["defaults"]["max_live_per_user"] == 3
    assert body["defaults"]["delete_after_days"] == 14 and "memory_mb" in body["bounds"]
    # read for support, write for platform admins only; customers are refused outright
    assert (await support.get("/admin/preview-limits")).status_code == 200
    assert (await support.put("/admin/preview-limits", json={"kill_switch": True})).status_code == 403
    assert (await customer.get("/admin/preview-limits")).status_code in (401, 403)
    assert (await customer.put("/admin/preview-limits", json={"kill_switch": True})).status_code in (401, 403)
    # validation: out-of-range and unknown keys are 422
    for bad in ({"memory_mb": 99999}, {"cpus": 0}, {"db_mb": 1}, {"delete_after_days": 0}, {"bogus": 1}):
        r = await admin.put("/admin/preview-limits", json={"defaults": bad})
        assert r.status_code == 422, bad
    ok = await admin.put(
        "/admin/preview-limits", json={"defaults": {"sleep_after_minutes": 10, "rate_per_minute": 60}}
    )
    assert ok.status_code == 200 and ok.json()["defaults"]["sleep_after_minutes"] == 10
    assert ok.json()["defaults"]["max_live_per_user"] == 3  # untouched keys keep their value
    missing = await admin.get(f"/admin/preview-limits/orgs/{uuid.uuid4()}")
    assert missing.status_code == 404
    # every change is audit-logged with its actor
    async with session_factory() as s:
        actions = [a.action for a in (await s.execute(select(AuditLog))).scalars()]
    assert actions.count("admin.preview_limits_update") == 1


async def test_self_host_kit_has_compose_guide_and_no_secrets(
    client: AsyncClient, stack: dict[str, object]
) -> None:
    pid = await _project_with_entity(client)
    r = await client.get(f"/projects/{pid}/generate/self-host-kit")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(BytesIO(r.content)).namelist()
    root = names[0].split("/")[0]
    assert {f"{root}/docker-compose.yml", f"{root}/SELF-HOST.md", f"{root}/Dockerfile"} <= set(names)
    z = zipfile.ZipFile(BytesIO(r.content))
    guide = z.read(f"{root}/SELF-HOST.md").decode()
    assert "docker compose up" in guide and "no secrets" in guide
    blob = b"".join(z.read(n) for n in names)
    assert b"api-test-secret-key" not in blob and b"BEGIN PRIVATE KEY" not in blob


# -- fix round: SENTINEL B3-10 findings --------------------------------------------------------


async def test_wake_waits_for_a_running_teardown_and_never_overlaps(
    client: AsyncClient, anon: AsyncClient, stack: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """M1: a request that arrives while the old stack is being torn down must not start the new
    stack until the teardown is finished, and the old teardown must never run after the launch."""
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    events: list[str] = []
    gate = asyncio.Event()

    async def slow_teardown(_b: object, db: str, app_: str) -> None:
        events.append("teardown-start")
        await gate.wait()
        events.append("teardown-end")

    async def launch(_b: object, spec: rt.StackSpec, _s: Settings) -> str:
        events.append("launch")
        return "127.0.0.1"

    monkeypatch.setattr(rt, "teardown", slow_teardown)
    monkeypatch.setattr(rt, "launch", launch)
    sleeper = asyncio.create_task(ps.sleep_preview(uuid.UUID(str(c["id"]))))
    await asyncio.sleep(0.2)
    row = (await client.get(f"/projects/{pid}/previews/{c['id']}")).json()
    assert row["state"] == "stopping"
    req = asyncio.create_task(
        anon.get(f"/previews/{c['id']}/items", headers={TOKEN: str(c["token"])})
    )
    await asyncio.sleep(1.0)
    assert events == ["teardown-start"]  # the wake is waiting, not launching
    gate.set()
    await sleeper
    r = await req
    assert r.status_code == 200
    assert events == ["teardown-start", "teardown-end", "launch"]


async def test_workspace_copy_never_carries_symlink_targets(tmp_path: Path) -> None:
    """M2: a symlink in a worktree (to a host file or a directory) is removed, not dereferenced."""
    secret = tmp_path / "host_secret.txt"
    secret.write_text("TOP-SECRET-HOST-FILE")
    other = tmp_path / "other_tenant"
    other.mkdir()
    (other / "code.py").write_text("OTHER-TENANT")
    src = tmp_path / "wt"
    (src / "app").mkdir(parents=True)
    (src / "app" / "main.py").write_text("print('ok')")
    (src / "app" / "passwd").symlink_to(secret)
    (src / "app" / "dirlink").symlink_to(other)
    (src / ".git").mkdir()
    (src / ".git" / "config").write_text("x")
    dest = tmp_path / "pv" / "code"
    ps.PreviewService._write_code(dest, {}, src)
    assert (dest / "app" / "main.py").read_text() == "print('ok')"
    assert not os.path.lexists(dest / "app" / "passwd")
    assert not os.path.lexists(dest / "app" / "dirlink")
    assert not (dest / ".git").exists()
    blob = "".join(p.read_text() for p in dest.rglob("*") if p.is_file())
    assert "TOP-SECRET" not in blob and "OTHER-TENANT" not in blob


async def test_kill_switch_acts_immediately_without_the_scheduler(
    client: AsyncClient, stack: dict[str, object], client_for: ClientFor
) -> None:
    """M3: toggling the switch stops running previews at once (no explicit sweep call)."""
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    admin = await client_for("root@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN)
    assert (await admin.put("/admin/preview-limits", json={"kill_switch": True})).status_code == 200
    await asyncio.gather(*list(ps._tasks))
    assert (await client.get(f"/projects/{pid}/previews/{c['id']}")).json()["state"] == "killed"
    assert stack["teardowns"]  # type: ignore[truthy-bool]


async def test_expiry_runs_lazily_when_the_scheduler_is_off(
    client: AsyncClient, stack: dict[str, object], session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    settings = stack["settings"]
    settings.preview_lazy_sweep = True  # type: ignore[attr-defined]
    try:
        pid = await _project_with_entity(client)
        c = await _create(client, pid)
        await _wait_state(client, pid, str(c["id"]), "running")
        async with session_factory() as s:
            await s.execute(
                update(Preview).where(Preview.id == uuid.UUID(str(c["id"])))
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )  # fmt: skip
            await s.commit()
        ps._last_lazy = 0.0
        await client.get(f"/projects/{pid}/previews")  # any preview API call starts the sweep
        await asyncio.gather(*list(ps._tasks))
        assert (await client.get(f"/projects/{pid}/previews/{c['id']}")).json()["state"] == "expired"
        # rate-limited: a second call inside the interval starts nothing
        before = len(stack["teardowns"])  # type: ignore[arg-type]
        await client.get(f"/projects/{pid}/previews")
        assert not ps._tasks and len(stack["teardowns"]) == before  # type: ignore[arg-type]
    finally:
        settings.preview_lazy_sweep = False  # type: ignore[attr-defined]


async def test_odd_proxy_paths_are_400_or_stay_inside_the_app(
    client: AsyncClient, anon: AsyncClient, stack: dict[str, object]
) -> None:
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    h = {TOKEN: str(c["token"])}
    for tail in ("//evil.example/x", "/a%3Fb%23c", "/%2e%2e/admin", "/x%00y", "/a%0d%0ab", "/caf%C3%A9"):
        r = await anon.get(f"/previews/{c['id']}{tail}", headers=h)
        assert r.status_code in (200, 400, 404, 422), (tail, r.status_code)
    ok = await anon.get(f"/previews/{c['id']}/a%3Fb%23c", headers=h)
    assert ok.status_code == 200 and ok.json()["target"] == "/a%3Fb%23c"  # not a query/fragment
    double = await anon.get(f"/previews/{c['id']}//evil.example/x", headers=h)
    assert double.status_code == 200 and double.json()["target"] == "//evil.example/x"


async def test_preview_responses_cannot_act_in_the_platform_origin(
    client: AsyncClient, anon: AsyncClient, stack: dict[str, object]
) -> None:
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    h = {TOKEN: str(c["token"])}
    for tail in ("/items", "/svg/logo"):
        r = await anon.get(f"/previews/{c['id']}{tail}", headers=h)
        low = {k.lower() for k in r.headers}
        for bad in ("location", "access-control-allow-origin", "access-control-allow-credentials", "link", "refresh", "set-cookie"):
            assert bad not in low, (tail, bad)
        assert r.headers["content-security-policy"].startswith("sandbox")
        assert "nosniff" in r.headers["x-content-type-options"]
    svg = await anon.get(f"/previews/{c['id']}/svg/logo", headers=h)
    assert svg.headers["content-disposition"] == "attachment"
    assert "content-disposition" not in (await anon.get(f"/previews/{c['id']}/items", headers=h)).headers


async def test_log_stream_honours_kill_switch_rate_cap_and_redacts_more(
    client: AsyncClient, anon: AsyncClient, stack: dict[str, object], client_for: ClientFor,
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    box: FakeBox = stack["box"]  # type: ignore[assignment]
    fakes = [
        "sk_" + "live_" + "abcdefghijklmnop",
        "ghp_" + "abcdefghijklmnopqrstuvwxyz0123",
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "eyJhbGciOiJI" + "UzI1NiJ9." + "eyJzdWIiOiIxMjM0NTY3" + "." + "SflKxwRJSMeKKF2QT4",
        "bbp_" + "abcdefghijklmnopqrstuvwxyz",
    ]
    box.log_text = (
        "Authorization: Bearer " + "q" * 12 + "\n"
        + "token " + fakes[3] + "\n" + "key " + fakes[0] + " " + fakes[1] + " " + fakes[2] + " " + fakes[4] + "\n"
        + "mysql://root:" + "pass" + "word123@host/db\n" + "plain\n"
    )
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    h = {TOKEN: str(c["token"])}
    url = f"/previews/{c['id']}/-/logs"
    r = await anon.get(url, headers=h)
    assert "plain" in r.text
    for f in [*fakes, "q" * 12, "pass" + "word123"]:
        assert f not in r.text, f
    # rate cap applies to opening streams
    async with session_factory() as s:
        row = await s.get(Preview, uuid.UUID(str(c["id"])))
        assert row is not None
        row.limits = {**row.limits, "rate_per_minute": 1}
        await s.commit()
    api_windows = __import__("app.api.previews", fromlist=["_windows"])._windows
    api_windows.clear()
    assert (await anon.get(url, headers=h)).status_code == 200
    assert (await anon.get(url, headers=h)).status_code == 429
    # kill switch
    admin = await client_for("root@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN)
    await admin.put("/admin/preview-limits", json={"kill_switch": True})
    api_windows.clear()
    assert (await anon.get(url, headers=h)).status_code == 503


async def test_org_override_cannot_exceed_default_without_the_flag_and_admin_lists(
    client: AsyncClient, stack: dict[str, object], client_for: ClientFor,
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    pid = await _project_with_entity(client)
    admin = await client_for("root@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN)
    support = await client_for("help@example.com", PlatformRole.platform_support, audience=sec.AUDIENCE_ADMIN)
    async with session_factory() as s:
        org_id = (await s.get(Project, uuid.UUID(pid))).organization_id  # type: ignore[union-attr]
    url = f"/admin/preview-limits/orgs/{org_id}"
    r = await admin.put(url, json={"overrides": {"memory_mb": 1024}})
    assert r.status_code == 422 and r.json()["code"] == "above_default"
    low = await admin.put(url, json={"overrides": {"memory_mb": 256}, "note": "small"})
    assert low.status_code == 200 and low.json()["effective"]["memory_mb"] == 256
    hi = await admin.put(url, json={"overrides": {"memory_mb": 1024}, "allow_above_default": True})
    assert hi.status_code == 200 and hi.json()["effective"]["memory_mb"] == 1024
    assert hi.json()["allow_above_default"] is True
    # lowering the platform default later clamps an org that has no flag
    await admin.put(url, json={"overrides": {"memory_mb": 512}})
    await admin.put("/admin/preview-limits", json={"defaults": {"memory_mb": 384}})
    assert (await admin.get(url)).json()["effective"]["memory_mb"] == 384
    # paginated list of overrides + usage counters (support may read)
    lst = await support.get("/admin/preview-limits/orgs?limit=10&offset=0")
    assert lst.status_code == 200
    body = lst.json()
    assert body["total"] == 1 and body["limit"] == 10 and body["offset"] == 0
    row = body["items"][0]
    assert row["organization_id"] == str(org_id) and row["overrides"] == {"memory_mb": 512}
    assert {"organization_name", "organization_slug", "enabled", "allow_above_default", "note", "updated_at"} <= set(row)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    u = (await support.get("/admin/preview-limits/usage")).json()
    assert u["live"] == 1 and u["running"] == 1 and u["by_state"]["running"] == 1
    assert u["orgs_with_overrides"] == 1 and u["kill_switch"] is False
    assert (await support.put(url, json={})).status_code == 403
