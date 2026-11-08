"""Postgres row-level security (PLATFORM_SAAS_PLAN §3.3, §9), Phase F.

The test database user is a superuser, which no policy binds. So every check that needs the
policy to bite runs as `rls_probe` (NOSUPERUSER, NOBYPASSRLS), switched in with SET ROLE. The
policies are installed and enabled here, in the throwaway test database only, and removed again.
"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.core import rls
from tests.api._auth_helpers import make_entity, make_project
from tests.api._routes import all_routes
from tests.api.conftest import ClientFor

ROLE = "rls_probe"


@pytest.fixture
async def rls_on(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') "
                f"THEN CREATE ROLE {ROLE} NOSUPERUSER NOBYPASSRLS NOLOGIN; END IF; END $$"
            )
        )
        await conn.execute(text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {ROLE}"))
        await conn.execute(text(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {ROLE}"))
        await rls.run(conn, rls.install_statements())
        await rls.run(conn, rls.enable_statements())
    yield
    async with engine.begin() as conn:
        await rls.run(conn, rls.disable_statements())
        await rls.run(conn, rls.uninstall_statements())


@pytest.fixture
def flag_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("BUILDER_RLS_ENABLED", "true")
    get_settings.cache_clear()
    yield
    rls.remove_hook()
    get_settings.cache_clear()


async def _two_orgs(client_for: ClientFor) -> tuple[AsyncClient, AsyncClient, str, str, str, str]:
    a = await client_for("a@example.com")
    b = await client_for("b@example.com")
    pa, pb = await make_project(a, "A-proj"), await make_project(b, "B-proj")
    await make_entity(a, pa, "AEntity")
    await make_entity(b, pb, "BEntity")
    oa = (await a.get("/orgs")).json()["items"][0]["id"]
    ob = (await b.get("/orgs")).json()["items"][0]["id"]
    return a, b, pa, pb, oa, ob


@asynccontextmanager
async def _probe(engine: AsyncEngine, org: str | None = None) -> AsyncIterator[AsyncConnection]:
    """A connection acting as the policy-bound role. Both settings are session-level, so they
    are reset before the connection goes back to the pool."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET ROLE {ROLE}"))
        if org is not None:
            await conn.execute(
                text("SELECT set_config('app.organization_id', :o, false)"), {"o": org}
            )
        try:
            yield conn
        finally:
            await conn.rollback()
            await conn.execute(text("RESET ROLE"))
            await conn.execute(text("RESET app.organization_id"))
            await conn.commit()


async def _as_probe(engine: AsyncEngine, org: str | None, sql: str) -> list[Any]:
    async with _probe(engine, org) as conn:
        return list((await conn.execute(text(sql))).all())


# -- the policies ---------------------------------------------------------------------------


async def test_status_lists_every_table_with_policy_and_switch(
    engine: AsyncEngine, rls_on: None
) -> None:
    async with engine.connect() as conn:
        info = await rls.status(conn)
    assert set(info) == set(rls.ALL_TABLES)
    assert all(v == {"policy": True, "enabled": True, "forced": True} for v in info.values())


async def test_a_scoped_transaction_sees_only_its_own_org(
    client_for: ClientFor, engine: AsyncEngine, rls_on: None
) -> None:
    _, _, pa, pb, oa, ob = await _two_orgs(client_for)
    rows = await _as_probe(engine, oa, "SELECT id::text FROM projects")
    assert [r[0] for r in rows] == [pa]
    rows = await _as_probe(engine, ob, "SELECT id::text FROM projects")
    assert [r[0] for r in rows] == [pb]
    # the org tables and the org row itself follow the same rule
    assert len(await _as_probe(engine, oa, "SELECT 1 FROM organization_members")) == 1
    assert [r[0] for r in await _as_probe(engine, oa, "SELECT id::text FROM organizations")] == [oa]
    assert len(await _as_probe(engine, oa, "SELECT 1 FROM subscriptions")) == 1


async def test_project_children_follow_their_project(
    client_for: ClientFor, engine: AsyncEngine, rls_on: None
) -> None:
    _, _, pa, _, oa, _ = await _two_orgs(client_for)
    rows = await _as_probe(engine, oa, "SELECT name, project_id::text FROM entities")
    assert rows == [("AEntity", pa)]
    members = await _as_probe(engine, oa, "SELECT project_id::text FROM project_members")
    assert [m[0] for m in members] == [pa]


async def test_audit_rows_of_other_orgs_are_hidden_but_platform_rows_are_not(
    client_for: ClientFor, engine: AsyncEngine, rls_on: None
) -> None:
    a, b, _, _, oa, ob = await _two_orgs(client_for)
    await a.patch(
        "/orgs/" + (await a.get("/orgs")).json()["items"][0]["slug"] + "/policies", json={}
    )
    rows = await _as_probe(
        engine, oa, "SELECT DISTINCT organization_id::text FROM platform_audit_log"
    )
    assert ob not in {r[0] for r in rows}


async def test_without_a_scope_nothing_is_confined(
    client_for: ClientFor, engine: AsyncEngine, rls_on: None
) -> None:
    """Sign-in, webhooks and the operator console run unscoped, as they always did."""
    await _two_orgs(client_for)
    assert len(await _as_probe(engine, None, "SELECT 1 FROM projects")) == 2


async def test_a_scoped_transaction_cannot_write_into_another_org(
    client_for: ClientFor, engine: AsyncEngine, rls_on: None
) -> None:
    _, _, pa, pb, oa, ob = await _two_orgs(client_for)
    async with _probe(engine, oa) as conn:
        done = await conn.execute(text("UPDATE projects SET name = 'x' WHERE id = :p"), {"p": pb})
        assert done.rowcount == 0  # B's row is invisible, so there is nothing to update
        deleted = await conn.execute(text("DELETE FROM projects WHERE id = :p"), {"p": pb})
        assert deleted.rowcount == 0
        with pytest.raises(DBAPIError):  # a new row for B is refused outright
            await conn.execute(
                text(
                    "INSERT INTO projects (id, name, slug, organization_id, created_at, updated_at)"
                    " VALUES (:i, 'evil', 'evil', :o, now(), now())"
                ),
                {"i": uuid.uuid4(), "o": ob},
            )


async def test_set_local_does_not_outlive_its_transaction(
    client_for: ClientFor, engine: AsyncEngine, rls_on: None
) -> None:
    """The reason for set_config(..., true): a pooled connection never carries the scope on."""
    _, _, _, _, oa, _ = await _two_orgs(client_for)
    async with _probe(engine) as conn:
        await conn.execute(text("SELECT set_config('app.organization_id', :o, true)"), {"o": oa})
        assert len((await conn.execute(text("SELECT 1 FROM projects"))).all()) == 1
        await conn.commit()
        assert len((await conn.execute(text("SELECT 1 FROM projects"))).all()) == 2


# -- the flag and the per-request binding ----------------------------------------------------


async def test_flag_is_off_by_default() -> None:
    assert get_settings().rls_enabled is False
    assert rls.is_enabled() is False


async def test_bind_does_nothing_while_the_flag_is_off(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        await db.execute(text("SELECT 1"))
        await rls.bind(db, uuid.uuid4())
        assert rls.current() is None
        value = (
            await db.execute(text("SELECT current_setting('app.organization_id', true)"))
        ).scalar()
        assert value in (None, "")


async def test_bind_sets_the_scope_now_and_again_after_every_commit(
    session_factory: async_sessionmaker[AsyncSession], flag_on: None
) -> None:
    org = uuid.uuid4()
    async with session_factory() as db:
        await db.execute(text("SELECT 1"))
        await rls.bind(db, org)
        read = text("SELECT current_setting('app.organization_id', true)")
        assert (await db.execute(read)).scalar() == str(org)
        await db.commit()
        # a handler commits and keeps going: the new transaction is bound again
        assert (await db.execute(read)).scalar() == str(org)
        await rls.release(db)
        assert (await db.execute(read)).scalar() in (None, "")
        await db.commit()
        assert (await db.execute(read)).scalar() in (None, "")
    rls.clear()


async def test_requests_under_rls_still_work_and_a_forgotten_filter_cannot_leak(
    client_for: ClientFor,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    rls_on: None,
    flag_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of defense in depth: the app talks to Postgres as a role the policies bind,
    and a handler that 'forgets' its org filter still returns only the caller's org."""
    a, b, pa, pb, oa, ob = await _two_orgs(client_for)
    slug_a = (await a.get("/orgs")).json()["items"][0]["slug"]

    @event.listens_for(session_factory.class_.sync_session_class, "after_begin")
    def as_probe(session: Any, transaction: Any, connection: Any) -> None:
        connection.execute(text(f"SET LOCAL ROLE {ROLE}"))

    try:
        # ordinary flows keep working with the policies on
        assert (await a.get(f"/orgs/{slug_a}/members")).status_code == 200
        assert (await a.get(f"/projects/{pa}")).status_code == 200
        assert (
            await a.patch(f"/projects/{pa}", json={"name": "renamed", "version": 1})
        ).status_code == 200
        assert (await a.get(f"/projects/{pb}")).status_code == 404

        # now break a handler on purpose: it lists projects with no organization filter
        from sqlalchemy import select

        from app.models.project import Project
        from app.services.organization_service import OrganizationService

        async def unfiltered(self: OrganizationService, *args: Any, **kwargs: Any) -> list[Any]:
            return list((await self.db.execute(select(Project))).scalars())

        listing = next(
            name
            for name in ("list_projects", "projects_of_org")
            if hasattr(OrganizationService, name)
        )
        monkeypatch.setattr(OrganizationService, listing, unfiltered)
        seen = (await a.get(f"/orgs/{slug_a}/projects")).json()
        ids = {p["id"] for p in (seen["items"] if isinstance(seen, dict) else seen)}
        assert pb not in ids
    finally:
        event.remove(session_factory.class_.sync_session_class, "after_begin", as_probe)


async def test_the_scope_does_not_leak_to_the_next_request_on_a_pooled_connection(
    engine: AsyncEngine, flag_on: None
) -> None:
    """SET LOCAL, not SET: one connection serves request after request."""
    one = create_async_engine(engine.url, pool_size=1, max_overflow=0)
    try:
        factory = async_sessionmaker(one, expire_on_commit=False)
        async with factory() as first:
            await first.execute(text("SELECT 1"))
            await rls.bind(first, uuid.uuid4())
            await first.commit()
        rls.clear()
        async with factory() as second:
            seen = (
                await second.execute(text("SELECT current_setting('app.organization_id', true)"))
            ).scalar()
        assert seen in (None, "")
    finally:
        await one.dispose()


async def test_moving_a_project_to_another_org_still_works_under_rls(
    client_for: ClientFor,
    session_factory: async_sessionmaker[AsyncSession],
    rls_on: None,
    flag_on: None,
) -> None:
    """The one org-scoped action that legitimately touches a second org lifts the scope."""
    owner = await client_for("mover@example.com")
    ids = {}
    for slug in ("one", "two"):
        made = await owner.post("/orgs", json={"name": slug, "slug": slug})
        assert made.status_code == 201, made.text
        ids[slug] = made.json()["id"]
    project = await owner.post("/projects", json={"name": "Mover", "organization_id": ids["one"]})
    assert project.status_code == 201, project.text

    @event.listens_for(session_factory.class_.sync_session_class, "after_begin")
    def as_probe(session: Any, transaction: Any, connection: Any) -> None:
        connection.execute(text(f"SET LOCAL ROLE {ROLE}"))

    try:
        moved = await owner.post(
            f"/orgs/one/projects/{project.json()['id']}/transfer", json={"to_slug": "two"}
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["organization_id"] != project.json()["organization_id"]
    finally:
        event.remove(session_factory.class_.sync_session_class, "after_begin", as_probe)


# -- the route walker: every org-scoped route binds the scope ---------------------------------


async def test_every_org_scoped_route_binds_the_scope(
    client_for: ClientFor, monkeypatch: pytest.MonkeyPatch, flag_on: None
) -> None:
    """Walks the app's real routes (tests/api/_routes.py): each /orgs/{slug}/… route, and each
    project route that names a project, must call rls.bind with the caller's org."""
    owner = await client_for("owner@example.com")
    created = await owner.post("/orgs", json={"name": "Acme", "slug": "acme"})
    org_id = created.json()["id"]
    bound: list[uuid.UUID] = []
    real_bind = rls.bind

    async def spy(db: AsyncSession, organization_id: uuid.UUID) -> None:
        bound.append(organization_id)
        await real_bind(db, organization_id)

    monkeypatch.setattr(rls, "bind", spy)
    # security.py imports the module, not the function, so the spy is seen
    missed: list[str] = []
    checked = 0
    for route in all_routes():
        path = route.path
        if path.startswith("/orgs/{slug}"):
            url = path.replace("{slug}", "acme")
        elif path.startswith("/projects/{project_id}") and "{" not in path.replace(
            "{project_id}", ""
        ):
            # a fresh project each time: DELETE /projects/{id} would otherwise remove the rest
            url = path.replace(
                "{project_id}", await make_project(owner, f"walk {uuid.uuid4().hex[:8]}")
            )
        else:
            continue
        url = _fill_rest(url)
        bound.clear()
        await owner.request(route.method, url, json={})
        checked += 1
        if not bound:
            missed.append(f"{route.method} {path}")
    assert checked > 40, f"walker only reached {checked} routes"
    # a route that answers before org_context resolves the org (bad path ids) is allowed to
    # skip; every route that reaches its handler must have bound
    assert missed == [], f"routes that never bound the RLS scope: {missed}"
    personal = next(
        o["id"] for o in (await owner.get("/orgs")).json()["items"] if o["kind"] == "personal"
    )
    assert set(bound) <= {uuid.UUID(org_id), uuid.UUID(personal)}
    rls.clear()


def _fill_rest(url: str) -> str:
    import re

    return re.sub(r"{(\w+)}", lambda _: str(uuid.uuid4()), url)


# -- the command line ------------------------------------------------------------------------


async def test_enable_needs_an_explicit_yes(capsys: pytest.CaptureFixture[str]) -> None:
    code = await rls._main("enable", yes=False)
    assert code == 1
    assert "--yes" in capsys.readouterr().out


def test_the_policy_lists_cover_every_table_with_an_org_column() -> None:
    from app.models import Base

    with_org = {t.name for t in Base.metadata.sorted_tables if "organization_id" in t.c}
    assert with_org <= set(rls.ALL_TABLES), with_org - set(rls.ALL_TABLES)
    with_project = {
        t.name
        for t in Base.metadata.sorted_tables
        if "project_id" in t.c and t.c.project_id.nullable is False and t.name != "projects"
    }
    assert with_project <= set(rls.ALL_TABLES), with_project - set(rls.ALL_TABLES)
