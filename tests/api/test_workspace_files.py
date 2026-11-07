"""E2: read/write file API of a draft workspace (custom zone editable, the rest read-only)."""

import hashlib
from typing import Any
import shutil
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.agent import AiRun
from app.models.platform import AuditLog
from app.services import workspace_service
from app.services.agent.wiring import content_hash
from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor, add_to_project_org

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

CUSTOM = "app/custom/notes.py"
SECRET_BODY = "print('body-marker-" "xyz')\n"


@pytest.fixture
def ws_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str) -> Settings:
    s = Settings(
        environment="test",
        workspace_root=str(tmp_path / "ws"),
        workspace_db_admin_url=SecretStr(database_url),
    )
    monkeypatch.setattr(workspace_service, "get_settings", lambda: s)
    return s


_MADE: list[str] = []  # workspace URLs to discard so no draft/checkpoint database outlives a test


@pytest.fixture(autouse=True)
async def _discard_workspaces(client: AsyncClient) -> Any:
    yield
    while _MADE:
        await client.delete(_MADE.pop())


async def _mk(client: AsyncClient, s: Settings) -> tuple[str, str, Path]:
    pid = await make_project(client)
    await make_entity(client, pid)
    r = await client.post(f"/projects/{pid}/workspaces", json={})
    assert r.status_code == 201, r.text
    ws = r.json()
    wt = Path(s.workspace_root or "") / pid / "wt" / ws["id"].replace("-", "")
    (wt / "app" / "custom").mkdir(parents=True, exist_ok=True)
    (wt / CUSTOM).write_text("print('v1')\n")
    _MADE.append(f"/projects/{pid}/workspaces/{ws['id']}")
    return pid, f"/projects/{pid}/workspaces/{ws['id']}", wt


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def test_list_and_read_zones(client: AsyncClient, ws_settings: Settings) -> None:
    pid, base, wt = await _mk(client, ws_settings)
    (wt / "link").symlink_to("/etc/passwd")
    r = await client.get(f"{base}/files")
    assert r.status_code == 200, r.text
    rows = r.json()
    paths = [x["path"] for x in rows]
    assert paths == sorted(paths) and not any(p.startswith(".git/") for p in paths)
    assert "link" not in paths
    by = {x["path"]: x for x in rows}
    assert by[CUSTOM] == {"path": CUSTOM, "zone": "custom", "size": 12, "editable": True}
    gen = next(p for p, x in by.items() if x["zone"] == "generated")
    assert by[gen]["editable"] is False
    got = await client.get(f"{base}/files/content", params={"path": CUSTOM})
    assert got.json() == {
        "path": CUSTOM, "zone": "custom", "content": "print('v1')\n",
        "editable": True, "sha256": _sha("print('v1')\n"),
    }  # fmt: skip
    g = await client.get(f"{base}/files/content", params={"path": gen})
    assert g.status_code == 200 and g.json()["editable"] is False


async def test_edit_rules(client: AsyncClient, ws_settings: Settings) -> None:
    pid, base, wt = await _mk(client, ws_settings)
    gen = next(x["path"] for x in (await client.get(f"{base}/files")).json() if x["zone"] == "generated")
    old = (await client.get(f"{base}/files/content", params={"path": gen})).json()["sha256"]
    r = await client.put(f"{base}/files/content", json={"path": gen, "content": "x", "expected_sha256": old})
    assert r.status_code == 403 and r.json()["code"] == "file_not_editable"
    cur = _sha("print('v1')\n")
    bad = await client.put(
        f"{base}/files/content", json={"path": CUSTOM, "content": SECRET_BODY, "expected_sha256": "0" * 64}
    )
    assert bad.status_code == 409 and bad.json()["code"] == "file_changed"
    assert (wt / CUSTOM).read_text() == "print('v1')\n"
    ok = await client.put(
        f"{base}/files/content", json={"path": CUSTOM, "content": SECRET_BODY, "expected_sha256": cur}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["sha256"] == _sha(SECRET_BODY) and (wt / CUSTOM).read_text() == SECRET_BODY
    assert not [p for p in (wt / "app" / "custom").iterdir() if p.name.startswith(".wsedit")]
    again = await client.put(  # the old hash is now stale
        f"{base}/files/content", json={"path": CUSTOM, "content": "z", "expected_sha256": cur}
    )
    assert again.status_code == 409


async def test_audit_has_no_content(
    client: AsyncClient, ws_settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid, base, _ = await _mk(client, ws_settings)
    r = await client.put(
        f"{base}/files/content",
        json={"path": CUSTOM, "content": SECRET_BODY, "expected_sha256": _sha("print('v1')\n")},
    )
    assert r.status_code == 200
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(AuditLog.action == "workspace.file.write"))).scalars().all()
    assert len(rows) == 1 and rows[0].detail is not None
    assert "body-marker" not in str(rows[0].detail) and rows[0].detail["path"] == CUSTOM


async def test_bad_paths_refused(client: AsyncClient, ws_settings: Settings) -> None:
    pid, base, wt = await _mk(client, ws_settings)
    outside = wt.parent / "outside.txt"
    outside.write_text("secret")
    (wt / "app" / "custom" / "esc.py").symlink_to(outside)
    (wt / "app" / "custom" / "dirlink").symlink_to(wt.parent, target_is_directory=True)
    for p in ("../outside.txt", "app/../../outside.txt", "/etc/passwd", ".git/config",
              "app/custom/esc.py", "app/custom/dirlink/outside.txt", "a\\b", "app//x"):  # fmt: skip
        g = await client.get(f"{base}/files/content", params={"path": p})
        assert g.status_code == 400 and g.json()["code"] == "bad_path", p
        w = await client.put(
            f"{base}/files/content", json={"path": p, "content": "x", "expected_sha256": "0" * 64}
        )
        assert w.status_code in (400, 403), p
    assert outside.read_text() == "secret"
    miss = await client.get(f"{base}/files/content", params={"path": "app/custom/none.py"})
    assert miss.status_code == 404 and miss.json()["code"] == "file_not_found"


async def test_binary_and_oversize(client: AsyncClient, ws_settings: Settings) -> None:
    pid, base, wt = await _mk(client, ws_settings)
    (wt / "app/custom/b.bin").write_bytes(b"\x00\x01\x02")
    (wt / "app/custom/latin.txt").write_bytes(b"\xff\xfe abc")
    (wt / "app/custom/big.txt").write_text("a" * (256 * 1024 + 1))
    for name, status, code in (("b.bin", 415, "file_not_text"), ("latin.txt", 415, "file_not_text"),
                               ("big.txt", 413, "file_too_large")):  # fmt: skip
        r = await client.get(f"{base}/files/content", params={"path": f"app/custom/{name}"})
        assert (r.status_code, r.json()["code"]) == (status, code)
    too = await client.put(
        f"{base}/files/content",
        json={"path": CUSTOM, "content": "é" * (130 * 1024), "expected_sha256": _sha("print('v1')\n")},
    )
    assert too.status_code in (413, 422)


async def test_roles_and_tenancy(client: AsyncClient, client_for: ClientFor, ws_settings: Settings) -> None:
    pid, base, _ = await _mk(client, ws_settings)
    viewer = await client_for("view@example.com")
    await add_to_project_org(pid, "view@example.com")
    m = await client.post(f"/projects/{pid}/members", json={"email": "view@example.com", "role": "viewer"})
    assert m.status_code == 201, m.text
    assert (await viewer.get(f"{base}/files")).status_code == 200
    assert (await viewer.get(f"{base}/files/content", params={"path": CUSTOM})).status_code == 200
    w = await viewer.put(
        f"{base}/files/content",
        json={"path": CUSTOM, "content": "x", "expected_sha256": _sha("print('v1')\n")},
    )
    assert w.status_code == 403
    other = await make_project(client, "Other")
    ws_id = base.rsplit("/", 1)[1]
    ob = f"/projects/{other}/workspaces/{ws_id}"
    assert (await client.get(f"{ob}/files")).status_code == 404
    assert (await client.get(f"{ob}/files/content", params={"path": CUSTOM})).status_code == 404
    put = await client.put(
        f"{ob}/files/content", json={"path": CUSTOM, "content": "x", "expected_sha256": "0" * 64}
    )
    assert put.status_code == 404


async def test_busy_workspace_and_stale_approval_hash(
    client: AsyncClient, ws_settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid, base, wt = await _mk(client, ws_settings)
    ws_id = uuid.UUID(base.rsplit("/", 1)[1])
    before = await content_hash(str(wt))  # what an approval would be bound to
    async with session_factory() as s:
        s.add(AiRun(project_id=uuid.UUID(pid), workspace_id=ws_id, goal="g", state="running"))
        await s.commit()
    body = {"path": CUSTOM, "content": "print('v2')\n", "expected_sha256": _sha("print('v1')\n")}
    r = await client.put(f"{base}/files/content", json=body)
    assert r.status_code == 409 and r.json()["code"] == "workspace_busy"
    assert await content_hash(str(wt)) == before
    async with session_factory() as s:
        run = (await s.execute(select(AiRun).where(AiRun.workspace_id == ws_id))).scalar_one()
        run.state = "applying"
        await s.commit()
    assert (await client.put(f"{base}/files/content", json=body)).status_code == 409
    async with session_factory() as s:
        run = (await s.execute(select(AiRun).where(AiRun.workspace_id == ws_id))).scalar_one()
        run.state = "stopped"
        await s.commit()
    assert (await client.put(f"{base}/files/content", json=body)).status_code == 200
    assert await content_hash(str(wt)) != before  # an approval bound to `before` is now stale
