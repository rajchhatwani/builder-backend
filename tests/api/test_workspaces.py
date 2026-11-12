"""B3-4: draft workspaces: create, checkpoint, rollback (code + spec ref + data), discard, access."""

import shutil
import subprocess
from pathlib import Path

import asyncpg
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from app.config import Settings
from app.services import workspace_service
from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor, add_to_project_org

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _pg_dsn(url: str, db: str) -> str:
    base = url.replace("postgresql+asyncpg", "postgresql").rsplit("/", 1)[0]
    return f"{base}/{db}"


@pytest.fixture
def ws_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str) -> Settings:
    s = Settings(
        environment="test",
        workspace_root=str(tmp_path / "ws"),
        workspace_db_admin_url=SecretStr(database_url),
    )
    monkeypatch.setattr(workspace_service, "get_settings", lambda: s)
    return s


async def _db_names(url: str) -> set[str]:
    conn = await asyncpg.connect(_pg_dsn(url, "postgres"))
    try:
        return {r["datname"] for r in await conn.fetch("SELECT datname FROM pg_database")}
    finally:
        await conn.close()


async def test_unconfigured_workspaces_answer_503(client: AsyncClient) -> None:
    pid = await make_project(client)
    assert (await client.post(f"/projects/{pid}/workspaces", json={})).status_code == 503


async def test_rollback_restores_code_spec_ref_and_data(
    client: AsyncClient, ws_settings: Settings, database_url: str
) -> None:
    pid = await make_project(client)
    await make_entity(client, pid)
    base = f"/projects/{pid}/workspaces"
    r = await client.post(base, json={"name": "try-things"})
    assert r.status_code == 201, r.text
    ws = r.json()
    assert ws["state"] == "active" and len(ws["checkpoints"]) == 1
    assert "database" not in r.text and "worktree" not in r.text  # no internals leaked
    first = ws["checkpoints"][0]
    assert first["has_data_snapshot"]

    wt = Path(ws_settings.workspace_root or "") / pid / "wt" / ws["id"].replace("-", "")
    assert (wt / ".git").exists() and any(wt.rglob("*.py"))
    db = f"bbws_{ws['id'].replace('-', '')}"
    assert db in await _db_names(database_url)

    # Work inside the draft: edit code, add a file, write data.
    marker = wt / "app" / "draft_edit.py"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("print('v1')\n")
    conn = await asyncpg.connect(_pg_dsn(database_url, db))
    await conn.execute("CREATE TABLE notes (v text); INSERT INTO notes VALUES ('one')")
    await conn.close()
    cp2 = await client.post(f"{base}/{ws['id']}/checkpoints", json={"label": "after one"})
    assert cp2.status_code == 201, cp2.text

    marker.write_text("print('v2')\n")
    (wt / "junk.txt").write_text("junk")
    conn = await asyncpg.connect(_pg_dsn(database_url, db))
    await conn.execute("INSERT INTO notes VALUES ('two'); CREATE TABLE extra (x int)")
    await conn.close()

    rb = await client.post(f"{base}/{ws['id']}/rollback", json={"checkpoint_id": cp2.json()["id"]})
    assert rb.status_code == 200, rb.text
    assert rb.json()["state"] == "rolled_back"
    assert marker.read_text() == "print('v1')\n" and not (wt / "junk.txt").exists()
    conn = await asyncpg.connect(_pg_dsn(database_url, db))
    rows = [r["v"] for r in await conn.fetch("SELECT v FROM notes ORDER BY v")]
    extra = await conn.fetchval("SELECT to_regclass('extra')")
    await conn.close()
    assert rows == ["one"] and extra is None

    # Roll all the way back to creation: draft file and table are gone.
    await client.post(f"{base}/{ws['id']}/rollback", json={"checkpoint_id": first["id"]})
    assert not marker.exists()
    conn = await asyncpg.connect(_pg_dsn(database_url, db))
    assert await conn.fetchval("SELECT to_regclass('notes')") is None
    await conn.close()

    # git history + tags exist for each checkpoint
    tags = subprocess.run(
        ["git", "tag"], cwd=wt, capture_output=True, text=True, check=True
    ).stdout.split()
    assert len(tags) == 2

    gone = await client.delete(f"{base}/{ws['id']}")
    assert gone.status_code == 200 and gone.json()["state"] == "discarded"
    assert not wt.exists()
    names = await _db_names(database_url)
    # Only THIS workspace's snapshots must be gone: other tests in the same session may still hold their own bbcp_* databases.
    own = {f"bbcp_{str(c['id']).replace('-', '')}" for c in [*ws["checkpoints"], first, cp2.json()]}
    assert db not in names and not (own & set(names))
    after = await client.post(f"{base}/{ws['id']}/checkpoints", json={"label": "x"})
    assert after.status_code == 409


async def test_checkpoint_after_discard_is_refused(
    client: AsyncClient, ws_settings: Settings
) -> None:
    pid = await make_project(client)
    await make_entity(client, pid)
    base = f"/projects/{pid}/workspaces"
    ws = (await client.post(base, json={})).json()
    await client.delete(f"{base}/{ws['id']}")
    r = await client.post(f"{base}/{ws['id']}/checkpoints", json={"label": "x"})
    assert r.status_code == 409
    rb = await client.post(
        f"{base}/{ws['id']}/rollback", json={"checkpoint_id": ws["checkpoints"][0]["id"]}
    )
    assert rb.status_code == 409


async def test_roles_and_isolation(
    client: AsyncClient, client_for: ClientFor, ws_settings: Settings
) -> None:
    pid = await make_project(client)
    await make_entity(client, pid)
    base = f"/projects/{pid}/workspaces"
    ws = (await client.post(base, json={})).json()
    viewer = await client_for("view@example.com")
    editor = await client_for("ed@example.com")
    for email, role in (("view@example.com", "viewer"), ("ed@example.com", "editor")):
        await add_to_project_org(pid, email)
        m = await client.post(f"/projects/{pid}/members", json={"email": email, "role": role})
        assert m.status_code == 201, m.text
    assert (await viewer.get(base)).status_code == 200
    assert (await viewer.post(base, json={})).status_code == 403
    assert (await viewer.delete(f"{base}/{ws['id']}")).status_code == 403
    assert (await editor.post(f"{base}/{ws['id']}/checkpoints", json={})).status_code == 201
    eve = await client_for("eve@example.com")
    assert (await eve.get(base)).status_code == 404
    assert (await eve.post(base, json={})).status_code == 404
    # wrong project / unknown workspace never leaks
    other_pid = await make_project(client, "Other")
    assert (await client.get(f"/projects/{other_pid}/workspaces/{ws['id']}")).status_code == 404


# -- SENTINEL B3-4 fix round -----------------------------------------------------------------


async def _mk(client: AsyncClient) -> tuple[str, str, dict]:
    pid = await make_project(client)
    await make_entity(client, pid)
    base = f"/projects/{pid}/workspaces"
    r = await client.post(base, json={})
    assert r.status_code == 201, r.text
    return pid, base, r.json()


def _wt(s: Settings, pid: str, ws: dict) -> Path:
    return Path(s.workspace_root or "") / pid / "wt" / ws["id"].replace("-", "")


async def test_quotas_workspace_checkpoint_disk_db(
    client: AsyncClient, ws_settings: Settings
) -> None:
    pid, base, ws = await _mk(client)
    ws_settings.workspace_max_active_per_project = 1
    r = await client.post(base, json={})
    assert r.status_code == 409 and r.json()["code"] == "workspace_limit"
    ws_settings.workspace_max_checkpoints = 1  # the "created" one already counts
    r = await client.post(f"{base}/{ws['id']}/checkpoints", json={})
    assert r.status_code == 409 and r.json()["code"] == "checkpoint_limit"
    ws_settings.workspace_max_checkpoints = 20
    ws_settings.workspace_max_db_bytes = 1
    r = await client.post(f"{base}/{ws['id']}/checkpoints", json={})
    assert r.status_code == 409 and r.json()["code"] == "workspace_db_quota"
    ws_settings.workspace_max_db_bytes = 1024**3
    ws_settings.workspace_max_disk_bytes = 10
    r = await client.post(f"{base}/{ws['id']}/checkpoints", json={})
    assert r.status_code == 409 and r.json()["code"] == "workspace_disk_quota"
    # refused operations leave the workspace usable
    ws_settings.workspace_max_disk_bytes = 200 * 1024**2
    assert (await client.post(f"{base}/{ws['id']}/checkpoints", json={})).status_code == 201


async def test_symlinks_and_git_files_refused(client: AsyncClient, ws_settings: Settings) -> None:
    pid, base, ws = await _mk(client)
    wt = _wt(ws_settings, pid, ws)
    (wt / "link").symlink_to("/etc/passwd")
    r = await client.post(f"{base}/{ws['id']}/checkpoints", json={})
    assert r.status_code == 422 and r.json()["code"] == "workspace_unsafe_files"
    (wt / "link").unlink()
    (wt / ".gitmodules").write_text("[submodule]")
    r = await client.post(f"{base}/{ws['id']}/checkpoints", json={})
    assert r.status_code == 422
    (wt / ".gitmodules").unlink()
    assert (await client.post(f"{base}/{ws['id']}/checkpoints", json={})).status_code == 201


async def test_project_lock_not_held_during_create(
    client: AsyncClient, ws_settings: Settings, monkeypatch: pytest.MonkeyPatch, session_factory
) -> None:
    from sqlalchemy import text

    seen: list[str] = []
    orig = workspace_service.WorkspaceService._git

    async def spy(self, cwd, *args):  # type: ignore[no-untyped-def]
        if not seen:
            async with session_factory() as s:  # another writer must not be blocked
                await s.execute(text("SET LOCAL lock_timeout = '500ms'"))
                await s.execute(text("SELECT id FROM projects FOR UPDATE NOWAIT"))
                seen.append("ok")
        return await orig(self, cwd, *args)

    monkeypatch.setattr(workspace_service.WorkspaceService, "_git", spy)
    await _mk(client)
    assert seen == ["ok"]


async def test_bad_template_name_is_refused(client: AsyncClient, ws_settings: Settings) -> None:
    ws_settings.workspace_template_db = 'x"; DROP DATABASE postgres; --'
    pid = await make_project(client)
    await make_entity(client, pid)
    assert (await client.post(f"/projects/{pid}/workspaces", json={})).status_code == 503


async def test_git_stderr_not_returned(ws_settings: Settings, tmp_path: Path) -> None:
    from app.exceptions import AppError

    svc = workspace_service.WorkspaceService(None, ws_settings)  # type: ignore[arg-type]
    (tmp_path / "ws").mkdir(exist_ok=True)
    with pytest.raises(AppError) as exc:
        await svc._git(tmp_path, "definitely-not-a-command")
    assert (
        "definitely-not-a-command" not in exc.value.message
        and str(tmp_path) not in exc.value.message
    )


async def test_discard_reports_partial_cleanup_and_can_retry(
    client: AsyncClient, ws_settings: Settings, monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    pid, base, ws = await _mk(client)
    orig = workspace_service.WorkspaceService._admin

    async def broken(self, *stmts):  # type: ignore[no-untyped-def]
        raise RuntimeError("db down")

    monkeypatch.setattr(workspace_service.WorkspaceService, "_admin", broken)
    r = await client.delete(f"{base}/{ws['id']}")
    assert r.status_code == 200
    assert r.json()["state"] == "discarded" and r.json()["cleanup_incomplete"] is True
    db = f"bbws_{ws['id'].replace('-', '')}"
    assert db in await _db_names(database_url)  # not forgotten
    monkeypatch.setattr(workspace_service.WorkspaceService, "_admin", orig)
    before = {n for n in await _db_names(database_url) if n.startswith("bbcp_")}
    r = await client.delete(f"{base}/{ws['id']}")
    assert r.json()["cleanup_incomplete"] is False
    names = await _db_names(database_url)
    assert db not in names
    assert len(before) - len({n for n in names if n.startswith("bbcp_")}) == len(ws["checkpoints"])


async def test_failed_rollback_changes_nothing(
    client: AsyncClient, ws_settings: Settings, monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    pid, base, ws = await _mk(client)
    db = f"bbws_{ws['id'].replace('-', '')}"
    conn = await asyncpg.connect(_pg_dsn(database_url, db))
    await conn.execute("CREATE TABLE keep (v int)")
    await conn.close()
    orig = workspace_service.WorkspaceService._git

    async def flaky(self, cwd, *args):  # type: ignore[no-untyped-def]
        if args[0] == "reset":
            raise RuntimeError("git exploded")
        return await orig(self, cwd, *args)

    monkeypatch.setattr(workspace_service.WorkspaceService, "_git", flaky)
    with pytest.raises(RuntimeError):
        await client.post(
            f"{base}/{ws['id']}/rollback", json={"checkpoint_id": ws["checkpoints"][0]["id"]}
        )
    conn = await asyncpg.connect(_pg_dsn(database_url, db))
    assert await conn.fetchval("SELECT to_regclass('keep')") is not None  # data untouched
    await conn.close()
    assert not any(n.startswith("bbtmp_") for n in await _db_names(database_url))
    cur = (await client.get(f"{base}/{ws['id']}")).json()
    assert cur["state"] == "active"  # restored from rolling_back
