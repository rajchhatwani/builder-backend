"""SEC M-1: the API must connect as a role RLS can bind (not superuser, not BYPASSRLS).

Unlike test_rls.py (which SET ROLEs from a superuser), this logs in as the real least-privilege
role created by `rls.app_role_statements`, the same statements `create-app-role` runs.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core import rls
from tests.api.conftest import ClientFor
from tests.api.test_rls import _two_orgs

ROLE = "builder_app_t"
PASSWORD = "app-role-test-password"


@pytest.fixture
async def app_engine(engine: AsyncEngine, database_url: str) -> AsyncGenerator[AsyncEngine, None]:
    url = make_url(database_url)
    stmts = rls.app_role_statements(
        ROLE, rls._quote(PASSWORD), url.username or "test", url.database or "test"
    )
    async with engine.begin() as conn:
        await rls.run(conn, stmts)
        await rls.run(conn, rls.install_statements())
        await rls.run(conn, rls.enable_statements())
    app = create_async_engine(url.set(username=ROLE, password=PASSWORD))
    yield app
    await app.dispose()
    async with engine.begin() as conn:
        await rls.run(conn, rls.disable_statements())
        await rls.run(conn, rls.uninstall_statements())
        await conn.execute(text(f"DROP OWNED BY {ROLE}"))
        await conn.execute(text(f"DROP ROLE {ROLE}"))


def test_role_statements_reject_unsafe_identifiers() -> None:
    with pytest.raises(ValueError):
        rls.app_role_statements("x; DROP TABLE users", "'p'", "owner", "db")
    assert rls._quote("it's") == "'it''s'"
    for bad in ["pa$$word-long-enough", "pass:word-long-enough", "back\\slash-long-enough"]:
        with pytest.raises(ValueError):
            rls._quote(bad)


async def test_superuser_connection_is_flagged_and_refused(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        problems = await rls.role_problems(conn)
    assert any("superuser" in p for p in problems)
    with pytest.raises(RuntimeError, match="BUILDER_RLS_ENABLED"):
        await rls.assert_role_enforces_rls(engine)


async def test_app_role_is_not_privileged_and_passes_the_startup_guard(
    app_engine: AsyncEngine,
) -> None:
    async with app_engine.connect() as conn:
        assert await rls.role_problems(conn) == []
    await rls.assert_role_enforces_rls(app_engine)


async def test_rls_really_hides_foreign_rows_for_the_login_role(
    app_engine: AsyncEngine, client_for: ClientFor
) -> None:
    _a, _b, _pa, _pb, org_a, org_b = await _two_orgs(client_for)
    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SELECT set_config('app.organization_id', :o, true)"), {"o": org_a})
            orgs = {str(r[0]) for r in await conn.execute(text("SELECT id FROM organizations"))}
            projects = (await conn.execute(text("SELECT count(*) FROM projects"))).scalar_one()
        assert orgs == {org_a} and org_b not in orgs
        assert projects == 1
