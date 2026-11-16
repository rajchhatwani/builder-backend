"""Audit B1-027: member-add oracle, last-owner/admin locks, early org deletion, MCP openapi,
org export truncation (F-0243..F-0247)."""

import threading
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.generator import engine
from app.exceptions import AppError
from app.models.platform import Organization, Subscription
from app.services import audit_service, org_deletion_service, org_export_service
from app.services.admin_service import AdminService
from app.services.member_service import MemberService
from app.services.mcp_service import McpService
from tests.api.conftest import ClientFor, MakeUser
from tests.api.test_mcp import _principal, _set_owner_mcp
from tests.api._auth_helpers import make_project

Factory = async_sessionmaker[AsyncSession]


async def test_member_add_outsider_and_unknown_look_the_same(
    client: AsyncClient, client_for: ClientFor
) -> None:
    """F-0243"""
    org = (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()["id"]
    pid = (await client.post("/projects", json={"name": "App", "organization_id": org})).json()[
        "id"
    ]
    await client_for("outsider@example.com")
    a = await client.post(
        f"/projects/{pid}/members", json={"email": "outsider@example.com", "role": "viewer"}
    )
    b = await client.post(
        f"/projects/{pid}/members", json={"email": "nobody@example.com", "role": "viewer"}
    )
    assert (a.status_code, a.json()["code"]) == (404, "user_unavailable")
    assert (b.status_code, b.json()["code"]) == (404, "user_unavailable")
    assert a.json() == b.json()


async def _captured(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    real = db.execute

    async def spy(stmt, *a, **k):  # type: ignore[no-untyped-def]
        seen.append(str(stmt.compile()))
        return await real(stmt, *a, **k)

    monkeypatch.setattr(db, "execute", spy)
    return seen


async def test_last_owner_check_locks_owner_rows(
    session_factory: Factory, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-0244 (members)"""
    async with session_factory() as db:
        seen = await _captured(db, monkeypatch)
        with pytest.raises(AppError):
            await MemberService(db)._require_another_owner(uuid.uuid4(), uuid.uuid4())
    assert any("FOR UPDATE" in s for s in seen)


async def test_last_admin_check_locks_admin_rows(
    session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-0244 (admins)"""
    async with session_factory() as db:
        seen = await _captured(db, monkeypatch)
        with pytest.raises(AppError):
            await AdminService(db, None)._require_another_admin(uuid.uuid4())  # type: ignore[arg-type]
    assert any("FOR UPDATE" in s for s in seen)


async def test_operator_early_delete_refuses_live_subscription(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    """F-0245"""
    from tests.api.test_org_deletion import _ops

    org = (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()["id"]
    assert (await client.delete("/orgs/acme")).status_code in (200, 202)
    async with session_factory() as session:
        sub = await session.get(Subscription, uuid.UUID(org))
        assert sub is not None
        sub.stripe_customer_id, sub.stripe_subscription_id = "cus_1", "sub_1"
        sub.status = "active"  # type: ignore[assignment]
        await session.commit()
    ops = await _ops(client_for)
    r = await ops.post(f"/admin/organizations/{org}/deletion/execute", json={"reason": "x"})
    assert r.status_code == 409, r.text
    async with session_factory() as session:
        row = await session.get(Organization, uuid.UUID(org))
        assert row is not None and row.deleted_at is None
        assert await org_deletion_service.run_due(session) == 0


async def test_mcp_get_openapi_runs_off_loop_and_maps_invalid_spec(
    client_for: ClientFor, session_factory: Factory, make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-0246"""
    owner = await client_for("owner@example.com")
    pid = await make_project(owner)
    await _set_owner_mcp(session_factory, uuid.UUID(pid), owner.user.id, True)  # type: ignore[attr-defined]
    main = threading.get_ident()
    threads: list[int] = []

    def fake(spec: object) -> dict[str, str]:
        threads.append(threading.get_ident())
        return {}

    monkeypatch.setattr(engine, "generate", fake)
    async with session_factory() as db:
        user = owner.user  # type: ignore[attr-defined]
        user = await db.merge(user)
        await McpService(db).get_openapi(await _principal(user), uuid.UUID(pid))
        assert threads and threads[0] != main

        def bad(spec: object) -> dict[str, str]:
            raise engine.InvalidSpecError("nope")

        monkeypatch.setattr(engine, "generate", bad)
        with pytest.raises(AppError) as ei:
            await McpService(db).get_openapi(await _principal(user), uuid.UUID(pid))
        assert ei.value.status_code == 422


async def test_org_export_keeps_newest_audit_rows_and_flags_truncation(
    client_for: ClientFor, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-0247"""
    monkeypatch.setattr(org_export_service, "AUDIT_LIMIT", 2)
    owner = await client_for("owner@example.com")
    org = (await owner.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()["id"]
    async with session_factory() as session:
        for n in range(3):
            await audit_service.record(
                session, action=f"test.event{n}", organization_id=uuid.UUID(org)
            )
        await session.commit()
    doc = (await owner.get("/orgs/acme/export")).json()
    assert doc["audit_truncated"] is True
    actions = [a["action"] for a in doc["audit"]]
    assert len(actions) == 2 and actions[-1] == "test.event2"
