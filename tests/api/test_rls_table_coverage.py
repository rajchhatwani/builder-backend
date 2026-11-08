"""S2-010: a table that carries org scope cannot be forgotten by the RLS list.

Org scope = an `organization_id` or `project_id` column, or a foreign key to a table that is
already in the RLS list. Everything else must be on the explicit allow-list below, with a reason.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core import rls
from app.models import Base
from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor
from tests.api.test_rls import ROLE, _as_probe, rls_on  # noqa: F401

# Platform- or user-level tables: no organization of their own, never confined per org.
PLATFORM_OR_USER_LEVEL: dict[str, str] = {
    "platform_users": "accounts belong to people, not to one org",
    "platform_refresh_tokens": "per user session",
    "platform_api_tokens": "per user token; org check happens on use",
    "platform_email_verification_tokens": "per user sign-up",
    "mfa_recovery_codes": "per user",
    "plans": "global catalogue",
    "ai_platform_budget": "platform-wide spend cap",
    "preview_platform_settings": "platform-wide preview limits",
}


def _foreign_tables(table: object) -> set[str]:
    return {fk.column.table.name for fk in table.foreign_keys}  # type: ignore[attr-defined]


def test_every_org_scoped_table_is_in_the_rls_list_or_allow_listed() -> None:
    covered = set(rls.ALL_TABLES)
    missing = []
    for t in Base.metadata.sorted_tables:
        if t.name in covered or t.name in PLATFORM_OR_USER_LEVEL:
            continue
        scoped = (
            "organization_id" in t.c or "project_id" in t.c or bool(_foreign_tables(t) & covered)
        )
        if scoped:
            missing.append(t.name)
        else:
            missing.append(f"{t.name} (no org link at all: add it to PLATFORM_OR_USER_LEVEL)")
    assert not missing, f"add to app/core/rls.py or the documented allow-list: {missing}"


def test_allow_list_has_no_stale_or_covered_entries() -> None:
    names = {t.name for t in Base.metadata.sorted_tables}
    assert set(PLATFORM_OR_USER_LEVEL) <= names
    assert not set(PLATFORM_OR_USER_LEVEL) & set(rls.ALL_TABLES)


def test_the_two_s2_010_tables_are_in_the_install_statements() -> None:
    sql = "\n".join(rls.install_statements())
    assert "ON fields USING" in sql and "ON scim_group_members USING" in sql


async def test_fields_and_scim_members_are_confined_to_their_org(
    client_for: ClientFor, engine: AsyncEngine, rls_on: None  # noqa: F811
) -> None:
    a = await client_for("a@example.com")
    b = await client_for("b@example.com")
    pa, pb = await make_project(a, "A"), await make_project(b, "B")
    ea, eb = await make_entity(a, pa, "AE"), await make_entity(b, pb, "BE")
    for client, ent, nm in ((a, ea, "afield"), (b, eb, "bfield")):
        r = await client.post(f"/entities/{ent}/fields", json={"name": nm, "type": "string"})
        assert r.status_code == 201, r.text
    oa = (await a.get("/orgs")).json()["items"][0]["id"]
    ob = (await b.get("/orgs")).json()["items"][0]["id"]
    assert [r[0] for r in await _as_probe(engine, oa, "SELECT name FROM fields")] == ["afield"]
    assert [r[0] for r in await _as_probe(engine, ob, "SELECT name FROM fields")] == ["bfield"]

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.platform import PlatformUser
    from app.models.scim import ScimGroup, ScimGroupMember, ScimUser

    factory = async_sessionmaker(engine, expire_on_commit=False)
    ga = uuid.uuid4()
    async with factory() as session:
        uid = {
            u.email: u.id for u in (await session.execute(select(PlatformUser))).scalars().all()
        }
        gb = uuid.uuid4()
        for org, g, email, tag in (
            (oa, ga, "a@example.com", "a"),
            (ob, gb, "b@example.com", "b"),
        ):
            su = ScimUser(organization_id=uuid.UUID(org), user_id=uid[email], user_name=tag)
            session.add_all([ScimGroup(id=g, organization_id=uuid.UUID(org), display_name=tag), su])
            await session.flush()
            session.add(ScimGroupMember(group_id=g, scim_user_id=su.id))
        await session.commit()
    rows = await _as_probe(engine, oa, "SELECT group_id::text FROM scim_group_members")
    assert [r[0] for r in rows] == [str(ga)]
    assert len(await _as_probe(engine, None, "SELECT 1 FROM scim_group_members")) == 2  # fail-open
