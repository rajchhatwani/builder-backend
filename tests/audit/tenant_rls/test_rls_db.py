"""Database-level wall: as the policy-bound role, scoped to the attacker's org, every project/org
table must show nothing of the victim's, reject writes into it, and reject planting rows."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core import rls
from tests.api.conftest import ClientFor
from tests.api.test_rls import _probe, rls_on  # noqa: F401  (fixture re-export)
from tests.audit.tenant_rls._world import two_orgs, victim_world


async def _org_id(c: object) -> str:
    return (await c.get("/orgs")).json()["items"][0]["id"]  # type: ignore[attr-defined]


async def test_every_project_table_hides_the_victims_rows_from_the_attacker_org(
    client_for: ClientFor, engine: AsyncEngine, rls_on: None,  # noqa: F811
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    a, b = await two_orgs(client_for)
    w = await victim_world(a, session_factory)
    pa = w["project_id"]
    ob = await _org_id(b)
    leaks = []
    checked = 0
    for table in rls.PROJECT_CHILD_TABLES:
        async with engine.connect() as raw:
            total = (
                await raw.execute(text(f'SELECT count(*) FROM "{table}" WHERE project_id = :p'), {"p": pa})
            ).scalar_one()
        if total == 0:
            continue  # nothing seeded for this table; the structural coverage test owns it
        checked += 1
        async with _probe(engine, ob) as conn:
            seen = (
                await conn.execute(text(f'SELECT count(*) FROM "{table}" WHERE project_id = :p'), {"p": pa})
            ).scalar_one()
            if seen:
                leaks.append(f"{table}: {seen} rows visible")
    assert checked >= 12, f"only {checked} tables had victim rows; the check would be vacuous"
    assert leaks == []


async def test_attacker_org_cannot_update_delete_or_plant_in_the_victims_rows(
    client_for: ClientFor, engine: AsyncEngine, rls_on: None,  # noqa: F811
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    a, b = await two_orgs(client_for)
    w = await victim_world(a, session_factory)
    pa, oa, ob = w["project_id"], await _org_id(a), await _org_id(b)
    async with _probe(engine, ob) as conn:
        upd = await conn.execute(text("UPDATE projects SET name = 'pwned' WHERE id = :p"), {"p": pa})
        assert upd.rowcount == 0
        dele = await conn.execute(text("DELETE FROM projects WHERE id = :p"), {"p": pa})
        assert dele.rowcount == 0
        for tbl in ("entities", "workspaces", "previews", "import_batches", "ai_runs"):
            r = await conn.execute(text(f'DELETE FROM "{tbl}" WHERE project_id = :p'), {"p": pa})
            assert r.rowcount == 0, tbl
        r = await conn.execute(text("UPDATE organizations SET name = 'pwned' WHERE id = :o"), {"o": oa})
        assert r.rowcount == 0
        r = await conn.execute(text("DELETE FROM organization_members WHERE organization_id = :o"), {"o": oa})
        assert r.rowcount == 0
    async with _probe(engine, ob) as conn:
        with pytest.raises(DBAPIError):  # planting a project into the victim's org
            await conn.execute(
                text(
                    "INSERT INTO projects (id, name, slug, organization_id, db_engine, version, created_at, updated_at) "
                    "VALUES (:i, 'plant', 'plant', :o, 'postgres', 1, now(), now())"
                ),
                {"i": str(uuid.uuid4()), "o": oa},
            )
    async with _probe(engine, ob) as conn:
        with pytest.raises(DBAPIError):  # planting a member row in the victim's org
            await conn.execute(
                text(
                    "INSERT INTO organization_members (organization_id, user_id, role, created_at) "
                    "VALUES (:o, :u, 'owner', now())"
                ),
                {"o": oa, "u": str(b.user.id)},  # type: ignore[attr-defined]
            )
    async with engine.connect() as raw:
        assert (await raw.execute(text("SELECT name FROM projects WHERE id = :p"), {"p": pa})).scalar_one() == "Victim"


async def test_fields_and_scim_children_follow_their_parent_org(
    client_for: ClientFor, engine: AsyncEngine, rls_on: None,  # noqa: F811
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    a, b = await two_orgs(client_for)
    w = await victim_world(a, session_factory)
    ob = await _org_id(b)
    async with _probe(engine, ob) as conn:
        n = (await conn.execute(text("SELECT count(*) FROM fields WHERE id = :f"), {"f": w["field_id"]})).scalar_one()
        assert n == 0
        n = (await conn.execute(text("SELECT count(*) FROM platform_audit_log WHERE project_id = :p"), {"p": w["project_id"]})).scalar_one()
        assert n == 0, "audit rows of the victim's project are visible to another org"


async def test_pooled_connection_does_not_carry_the_previous_orgs_scope(
    client_for: ClientFor, session_factory: async_sessionmaker,  # type: ignore[type-arg]
    engine: AsyncEngine,
) -> None:
    """Two orgs alternate over the same pool; an unscoped helper session afterwards must not
    inherit either org (`SET LOCAL` semantics)."""
    a, b = await two_orgs(client_for)
    for _ in range(3):
        await a.get("/projects")
        await b.get("/orgs")
    async with session_factory() as s:
        cur = (await s.execute(text("SELECT current_setting('app.organization_id', true)"))).scalar_one()
        assert cur in (None, ""), f"pooled connection kept scope {cur!r}"
