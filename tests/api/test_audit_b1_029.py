# ruff: noqa: F811, F401
"""Audit B1-029: SCIM token owner-only, atomic login lockout, last-owner lock, failed preview
sweep, SCIM e-mail PATCH, null PATCH on permissions, preview teardown on delete
(F-0252..F-0258)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.exceptions import AppError
from app.models.enums import OrgRole, TokenAudience
from app.models.platform import OrganizationMember, PlatformUser
from app.models.preview import Preview
from app.services import preview_service as ps
from app.services.organization_service import OrganizationService
from app.services.platform_auth_service import PlatformAuthService, RequestInfo
from tests.api._auth_helpers import make_entity, make_project, make_role
from tests.api.conftest import TEST_PASSWORD, ClientFor, MakeUser
from tests.api.test_previews import (  # noqa: F401  (stack is a fixture)
    TOKEN,
    _create,
    _project_with_entity,
    _wait_state,
    stack,
)
from tests.api.test_scim import dns, enterprise_org, scim_token  # noqa: F401  (dns is a fixture)

Factory = async_sessionmaker[AsyncSession]


async def _add_member(factory: Factory, org: str, client: AsyncClient, role: OrgRole) -> None:
    async with factory() as s:
        s.add(
            OrganizationMember(
                organization_id=uuid.UUID(org),
                user_id=client.user.id,  # type: ignore[attr-defined]
                role=role,
            )
        )
        await s.commit()


# -- F-0252 ------------------------------------------------------------------------------------


async def test_scim_token_is_owner_only(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    """F-0252: the bearer holds owner powers, so only an owner may mint or rotate it."""
    org = await enterprise_org(client, session_factory, dns)
    admin = await client_for("admin@example.com")
    await _add_member(session_factory, org, admin, OrgRole.admin)
    r = await admin.post("/orgs/acme/scim/token")
    assert r.status_code == 403 and r.json()["code"] == "org_role_required", r.text
    await scim_token(client)  # the owner may
    r = await admin.post("/orgs/acme/scim/token")  # rotation too
    assert r.status_code == 403, r.text


# -- F-0253 ------------------------------------------------------------------------------------


async def test_parallel_wrong_passwords_trip_the_lockout(
    session_factory: Factory, make_user: MakeUser
) -> None:
    """F-0253: failed_logins is bumped atomically; N parallel guesses must not lose updates."""
    user = await make_user("victim@example.com")
    settings = Settings(environment="test", login_max_failures=4, lockout_minutes=15)

    async def guess() -> None:
        async with session_factory() as db:
            with pytest.raises(AppError):
                await PlatformAuthService(db, settings).login(
                    email="victim@example.com",
                    password="wrong-password-guess",
                    audience=TokenAudience.app,
                    info=RequestInfo(),
                )

    await asyncio.gather(*(guess() for _ in range(4)))
    async with session_factory() as db:
        row = await db.get(PlatformUser, user.id)
        assert row is not None
        assert row.locked_until is not None, f"lost updates: failed_logins={row.failed_logins}"


# -- F-0254 ------------------------------------------------------------------------------------


async def test_last_owner_check_locks_owner_rows(
    session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-0254 (org service): the owner set is locked before it is counted."""
    async with session_factory() as db:
        seen: list[str] = []
        real = db.execute

        async def spy(stmt, *a, **k):  # type: ignore[no-untyped-def]
            seen.append(str(stmt.compile()))
            return await real(stmt, *a, **k)

        monkeypatch.setattr(db, "execute", spy)
        with pytest.raises(AppError):
            await OrganizationService(db)._require_another_owner(uuid.uuid4(), uuid.uuid4())
    assert any("FOR UPDATE" in s and "organization_members" in s for s in seen), seen


async def test_scim_offboarding_locks_the_owner_set(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    """F-0254 (scim _leave)."""
    from tests.api.test_scim import SCIM, ops, provision

    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    seen: list[str] = []

    def spy(conn, cursor, statement, *a):  # type: ignore[no-untyped-def]
        if "FROM organization_members" in statement and "FOR UPDATE" in statement:
            seen.append(statement)

    event.listen(Engine, "before_cursor_execute", spy)
    try:
        r = await anon_client.patch(
            f"{SCIM}/Users/{uid}",
            json=ops({"op": "replace", "path": "active", "value": False}),
            headers=h,
        )
    finally:
        event.remove(Engine, "before_cursor_execute", spy)
    assert r.status_code == 200, r.text
    assert seen, "owner rows were not locked FOR UPDATE before the owner check"


# -- F-0255 ------------------------------------------------------------------------------------


async def test_sweep_expires_failed_previews_and_wipes_code(
    client: AsyncClient,
    stack: dict[str, object],
    session_factory: Factory,  # noqa: F811
) -> None:
    """F-0255"""
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    code_dir = Path(str(stack["settings"].preview_root)) / uuid.UUID(str(c["id"])).hex  # type: ignore[attr-defined]
    assert code_dir.exists()
    async with session_factory() as s:
        await s.execute(
            update(Preview)
            .where(Preview.id == uuid.UUID(str(c["id"])))
            .values(state="failed", expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    res = await ps.sweep()
    assert res.expired == 1
    assert not code_dir.exists()
    assert (await client.get(f"/projects/{pid}/previews/{c['id']}")).json()["state"] == "expired"


# -- F-0257 ------------------------------------------------------------------------------------


async def test_permission_patch_rejects_null_roles_and_inconsistent_filters(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    entity_id = await make_entity(client, project_id)
    await make_role(client, project_id, "member")
    perm = (
        await client.post(
            f"/projects/{project_id}/permissions",
            json={
                "permissions": [{"entity_id": entity_id, "operation": "list", "roles": ["member"]}]
            },
        )
    ).json()[0]
    r = await client.patch(f"/permissions/{perm['id']}", json={"roles": None})
    assert r.status_code == 422, r.text
    r = await client.patch(f"/permissions/{perm['id']}", json={"row_rule": "custom_filter"})
    assert r.status_code == 422, r.text
    r = await client.patch(f"/permissions/{perm['id']}", json={"custom_filter_field": "x"})
    assert r.status_code == 422, r.text
    ok = await client.patch(f"/permissions/{perm['id']}", json={"roles": ["member"]})
    assert ok.status_code == 200, ok.text


# -- F-0258 ------------------------------------------------------------------------------------


async def test_project_delete_tears_down_its_previews(
    client: AsyncClient,
    stack: dict[str, object],  # noqa: F811
) -> None:
    pid = await _project_with_entity(client)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    code_dir = Path(str(stack["settings"].preview_root)) / uuid.UUID(str(c["id"])).hex  # type: ignore[attr-defined]
    assert code_dir.exists()
    before = len(stack["teardowns"])  # type: ignore[arg-type]
    assert (await client.delete(f"/projects/{pid}")).status_code == 204
    assert len(stack["teardowns"]) == before + 1  # type: ignore[arg-type]
    assert not code_dir.exists()


async def test_org_deletion_tears_down_previews(
    client: AsyncClient,
    stack: dict[str, object],
    session_factory: Factory,  # noqa: F811
) -> None:
    org = (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()["id"]
    r = await client.post("/projects", json={"name": "App", "organization_id": org})
    pid = r.json()["id"]
    await make_entity(client, pid)
    c = await _create(client, pid)
    await _wait_state(client, pid, str(c["id"]), "running")
    before = len(stack["teardowns"])  # type: ignore[arg-type]
    async with session_factory() as db:
        await OrganizationService(db).execute_deletion(uuid.UUID(org))
    assert len(stack["teardowns"]) == before + 1  # type: ignore[arg-type]
    _ = (select, TEST_PASSWORD, TOKEN)


# -- F-0252 (b): admin group_roles PATCH must not demote SCIM-linked owners ----------------


async def test_admin_group_roles_patch_spares_scim_owners(
    client: AsyncClient,
    anon_client: AsyncClient,
    client_for: ClientFor,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    from tests.api.test_scim import SCIM, member_role, provision

    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    gid = (
        await anon_client.post(
            f"{SCIM}/Groups", json={"displayName": "Admins", "members": [{"value": uid}]}, headers=h
        )
    ).json()["id"]
    assert gid
    async with session_factory() as s:  # alice is a SCIM-linked owner; mapping is empty
        row = (
            await s.execute(
                select(OrganizationMember)
                .join(PlatformUser, PlatformUser.id == OrganizationMember.user_id)
                .where(
                    OrganizationMember.organization_id == uuid.UUID(org),
                    PlatformUser.email == "alice@acme.test",
                )
            )
        ).scalar_one()
        row.role = OrgRole.owner
        await s.commit()
    admin = await client_for("admin@example.com")
    await _add_member(session_factory, org, admin, OrgRole.admin)
    r = await admin.patch("/orgs/acme/scim", json={"group_roles": {"Admins": "admin"}})
    assert r.status_code == 200, r.text
    assert await member_role(session_factory, org, "alice@acme.test") is OrgRole.owner
