"""S2-017: DDL identifiers are fullmatched at the _admin boundary; datname is a bind parameter."""

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.exceptions import AppError
from app.services import workspace_service
from app.services.workspace_service import WorkspaceService

HOSTILE = ['x"; DROP DATABASE postgres; --', "a b", 'a"b', "x\n", "", "1abc", "a" * 64, "é"]


def _svc(tmp_path, url: str) -> WorkspaceService:  # type: ignore[no-untyped-def]
    s = Settings(
        environment="test", workspace_root=str(tmp_path), workspace_db_admin_url=SecretStr(url)
    )
    return WorkspaceService(None, s)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", HOSTILE)
async def test_hostile_identifier_refused_before_any_connection(name: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # an unreachable admin URL: reaching the connection would raise a different error
    svc = _svc(tmp_path, "postgresql+asyncpg://nobody:x@127.0.0.1:1/none")
    for stmts in (
        svc._clone(name, "tmpl", kick=False),
        svc._clone("fine_name", name, kick=False),
        [f'DROP DATABASE IF EXISTS "{name}"'],
        [f'ALTER DATABASE "tmp" RENAME TO "{name}"'],
    ):
        with pytest.raises(AppError) as exc:
            await svc._admin(*stmts)
        assert exc.value.code == "workspace_bad_identifier"


async def test_kick_binds_datname_and_cannot_widen(tmp_path, database_url: str) -> None:  # type: ignore[no-untyped-def]
    import asyncpg

    base = database_url.replace("postgresql+asyncpg", "postgresql").rsplit("/", 1)[0]
    victim = await asyncpg.connect(f"{base}/postgres")
    try:
        svc = _svc(tmp_path, database_url)
        await svc._admin(svc._kick("x' OR datname = 'postgres' --"))
        assert await victim.fetchval("SELECT 1") == 1  # still connected: the name was data
    finally:
        await victim.close()


async def test_valid_identifiers_still_work(tmp_path, database_url: str) -> None:  # type: ignore[no-untyped-def]
    svc = _svc(tmp_path, database_url)
    name = "bb_ident_ok_test"
    try:
        await svc._admin(f'CREATE DATABASE "{name}"')
    finally:
        await svc._admin(svc._kick(name), f'DROP DATABASE IF EXISTS "{name}"')
    assert workspace_service._DB_IDENT.fullmatch(name)
