"""P3: every workspace database gets its own LOGIN role that can reach only that database."""

import shutil
from pathlib import Path

import asyncpg
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from app.config import Settings
from app.services import workspace_service
from app.services.workspace_service import WorkspaceService
from tests.api._auth_helpers import make_project
from tests.api.test_workspaces import _pg_dsn

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
PW = "a1" * 16  # test-only password (hex, as the real generator produces)


async def _roles(url: str) -> set[str]:
    conn = await asyncpg.connect(_pg_dsn(url, "postgres"))
    try:
        return {r["rolname"] for r in await conn.fetch("SELECT rolname FROM pg_roles")}
    finally:
        await conn.close()


async def test_role_reaches_only_its_own_database(tmp_path: Path, database_url: str) -> None:
    s = Settings(
        environment="test", workspace_root=str(tmp_path), workspace_db_admin_url=SecretStr(database_url)
    )
    svc = WorkspaceService(None, s)  # type: ignore[arg-type]
    a, b = "bbws_" + "a" * 32, "bbws_" + "b" * 32
    try:
        for db in (a, b):
            await svc._admin(f'CREATE DATABASE "{db}"')
            await svc._grant_db_role(db, PW)
        role_a, role_b = svc.role_for(a), svc.role_for(b)
        assert role_a and role_b and role_a != role_b

        # the role works on its own database and owns it
        conn = await asyncpg.connect(_pg_dsn(database_url, a), user=role_a, password=PW)
        try:
            await conn.execute("CREATE TABLE t (v int)")
            attrs = await conn.fetchrow(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolreplication "
                "FROM pg_roles WHERE rolname = current_user"
            )
            assert not any(attrs)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute("CREATE ROLE sneaky")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute("CREATE DATABASE sneaky")
        finally:
            await conn.close()

        # ...but not on another workspace database, nor on the platform database, nor postgres
        # (a hardened server revokes PUBLIC's CONNECT on the platform database: 10-app-role.sql
        # and `create-app-role` do that; the test applies the same statement here)
        platform = database_url.replace("postgresql+asyncpg", "postgresql")
        platform_db = platform.rsplit("/", 1)[1].split("?")[0]
        await svc._admin(f'REVOKE CONNECT ON DATABASE "{platform_db}" FROM PUBLIC')
        try:
            for dsn in (_pg_dsn(database_url, b), platform):
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await asyncpg.connect(dsn, user=role_a, password=PW)
        finally:
            await svc._admin(f'GRANT CONNECT ON DATABASE "{platform_db}" TO PUBLIC')
        # PUBLIC may no longer connect to the workspace database either
        conn = await asyncpg.connect(_pg_dsn(database_url, a))
        try:
            assert await conn.fetchval(
                "SELECT has_database_privilege('public', $1, 'CONNECT')", a
            ) is False
        finally:
            await conn.close()

        # dropping the database drops the role
        assert await svc._drop_dbs([a]) == []
        assert role_a not in await _roles(database_url) and role_b in await _roles(database_url)
    finally:
        await svc._drop_dbs([a, b])


async def test_hostile_role_name_cannot_be_built() -> None:
    assert WorkspaceService.role_for('bbws_x"; DROP ROLE postgres; --') is None
    assert WorkspaceService.role_for("other_name") is None


async def test_create_makes_a_role_discard_and_failed_create_drop_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    s = Settings(
        environment="test", workspace_root=str(tmp_path / "ws"), workspace_db_admin_url=SecretStr(database_url)
    )
    monkeypatch.setattr(workspace_service, "get_settings", lambda: s)
    pid = await make_project(client)
    base = f"/projects/{pid}/workspaces"
    r = await client.post(base, json={"name": "roles"})
    assert r.status_code == 201, r.text
    ws_id = r.json()["id"]
    role = "bbwr_" + ws_id.replace("-", "")
    assert role in await _roles(database_url)
    assert "password" not in r.text.lower()
    d = await client.delete(f"{base}/{ws_id}")
    assert d.status_code in (200, 204), d.text
    assert role not in await _roles(database_url)

    # a create that fails after the role exists leaves no role behind
    async def boom(self: object, *a: object, **k: object) -> None:
        raise RuntimeError("checkpoint failed")

    monkeypatch.setattr(WorkspaceService, "_take_checkpoint", boom)
    before = await _roles(database_url)
    with pytest.raises(RuntimeError, match="checkpoint failed"):
        await client.post(base, json={"name": "fails"})
    assert {x for x in await _roles(database_url) if x.startswith("bbwr_")} == {
        x for x in before if x.startswith("bbwr_")
    }
