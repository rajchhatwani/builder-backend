"""Owner decisions, round 1.

1. A team org starts on the free plan; it moves up only by paying (Checkout → webhook) or
   when an operator onboards it (admin plan change).
2. Deleting an org is a request: access is blocked at once, the owner can revoke it during a
   grace period (default 7 days, an operator can set any period or delete early), and when
   the period ends the org and its projects are deleted.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_security as sec
from app.models.enums import PlatformRole
from app.models.platform import AuditLog, Organization, Subscription
from app.models.project import Project
from app.services import org_deletion_service
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]


# -- 1. team orgs start free -------------------------------------------------------------------


async def test_new_team_orgs_start_on_free(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import organization_service

    monkeypatch.setattr(organization_service, "DEFAULT_TEAM_PLAN_ID", "free")  # production
    org = (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()
    async with session_factory() as session:
        sub = await session.get(Subscription, uuid.UUID(org["id"]))
        assert sub is not None and sub.plan_id == "free"


def test_production_default_for_team_orgs_is_free() -> None:
    """The conftest patches it for feature tests; the shipped value must stay 'free'."""
    import importlib

    import app.services.organization_service as mod

    source = importlib.util.find_spec(mod.__name__).loader.get_source(mod.__name__)  # type: ignore[union-attr]
    assert 'DEFAULT_TEAM_PLAN_ID = "free"' in source


# -- 2. deletion requests ---------------------------------------------------------------------


async def _acme(client: AsyncClient, client_for: ClientFor) -> tuple[str, str, AsyncClient]:
    org = (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()["id"]
    pid = (await client.post("/projects", json={"name": "App", "organization_id": org})).json()[
        "id"
    ]
    bob = await client_for("bob@example.com")
    inv = await client.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    await bob.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    await client.post(
        f"/projects/{pid}/members", json={"email": "bob@example.com", "role": "editor"}
    )
    return org, pid, bob


async def test_owner_requests_deletion_and_access_is_blocked(
    client: AsyncClient, client_for: ClientFor
) -> None:
    _org, pid, bob = await _acme(client, client_for)
    r = await client.delete("/orgs/acme")
    assert r.status_code == 202, r.text
    body = r.json()
    scheduled = datetime.fromisoformat(body["deletion_scheduled_for"])
    assert timedelta(days=6, hours=23) < scheduled - datetime.now(UTC) <= timedelta(days=7)

    # Everyone loses access to the org and its projects, with one clear answer.
    for who in (client, bob):
        r = await who.get("/orgs/acme/members")
        assert r.status_code == 423
        assert r.json()["code"] == "org_deletion_pending"
        assert (await who.get(f"/projects/{pid}")).status_code == 423
    # The org itself stays visible so the UI can say what's happening.
    org = (await client.get("/orgs/acme")).json()
    assert org["deletion_scheduled_for"] == body["deletion_scheduled_for"]
    listed = (await bob.get("/orgs")).json()["items"]
    assert any(o["slug"] == "acme" and o["deletion_scheduled_for"] for o in listed)


async def test_only_owners_can_request_deletion(client: AsyncClient, client_for: ClientFor) -> None:
    _org, _pid, bob = await _acme(client, client_for)
    assert (await bob.delete("/orgs/acme")).status_code == 403


async def test_owner_can_revoke_the_request(client: AsyncClient, client_for: ClientFor) -> None:
    _org, pid, bob = await _acme(client, client_for)
    await client.delete("/orgs/acme")
    assert (await bob.post("/orgs/acme/deletion/cancel")).status_code == 403  # members can't
    r = await client.post("/orgs/acme/deletion/cancel")
    assert r.status_code == 200
    assert r.json()["deletion_scheduled_for"] is None
    assert (await bob.get(f"/projects/{pid}")).status_code == 200
    assert (await client.get("/orgs/acme/members")).status_code == 200


async def test_requesting_twice_is_refused(client: AsyncClient, client_for: ClientFor) -> None:
    await _acme(client, client_for)
    await client.delete("/orgs/acme")
    r = await client.delete("/orgs/acme")
    assert r.status_code == 423  # the org is already locked waiting for deletion
    assert r.json()["code"] == "org_deletion_pending"


async def test_live_billing_must_be_canceled_first(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org, _pid, _bob = await _acme(client, client_for)
    async with session_factory() as session:
        sub = await session.get(Subscription, uuid.UUID(org))
        assert sub is not None
        sub.stripe_customer_id, sub.stripe_subscription_id = "cus_1", "sub_1"
        await session.commit()
    r = await client.delete("/orgs/acme")
    assert r.status_code == 409
    assert r.json()["code"] == "org_has_billing"


async def test_personal_orgs_cannot_be_deleted(client: AsyncClient) -> None:
    slug = next(
        o["slug"] for o in (await client.get("/orgs")).json()["items"] if o["kind"] == "personal"
    )
    assert (await client.delete(f"/orgs/{slug}")).status_code == 403


async def test_due_deletions_run_when_the_period_ends(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org, pid, bob = await _acme(client, client_for)
    await client.delete("/orgs/acme")

    async with session_factory() as session:  # not due yet → nothing happens
        assert await org_deletion_service.run_due(session) == 0
    async with session_factory() as session:
        row = await session.get(Organization, uuid.UUID(org))
        assert row is not None
        row.deletion_scheduled_for = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    async with session_factory() as session:
        assert await org_deletion_service.run_due(session) == 1

    async with session_factory() as session:
        row = await session.get(Organization, uuid.UUID(org))
        assert row is not None and row.deleted_at is not None
        assert await session.get(Project, uuid.UUID(pid)) is None  # projects go with the org
        actions = set((await session.execute(select(AuditLog.action))).scalars())
        assert {"org.deletion_requested", "org.deleted"} <= actions
    assert (await client.get("/orgs/acme")).status_code == 404
    assert [o["kind"] for o in (await bob.get("/orgs")).json()["items"]] == ["personal"]


async def test_a_revoked_request_is_never_executed(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org, _pid, _bob = await _acme(client, client_for)
    await client.delete("/orgs/acme")
    await client.post("/orgs/acme/deletion/cancel")
    async with session_factory() as session:
        assert await org_deletion_service.run_due(session) == 0
        row = await session.get(Organization, uuid.UUID(org))
        assert row is not None and row.deleted_at is None


# -- operator controls ---------------------------------------------------------------------------


async def _ops(client_for: ClientFor) -> AsyncClient:
    return await client_for(
        "ops@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )


async def test_operator_sets_a_different_grace_period(
    client: AsyncClient, client_for: ClientFor
) -> None:
    org, _pid, _bob = await _acme(client, client_for)
    await client.delete("/orgs/acme")
    ops = await _ops(client_for)
    r = await ops.patch(
        f"/admin/organizations/{org}/deletion", json={"grace_days": 30, "reason": "legal hold"}
    )
    assert r.status_code == 200, r.text
    scheduled = datetime.fromisoformat(r.json()["deletion_scheduled_for"])
    assert scheduled - datetime.now(UTC) > timedelta(days=29)
    listed = (await ops.get("/admin/organizations?q=acme")).json()["items"][0]
    assert listed["deletion_scheduled_for"] is not None


async def test_operator_can_delete_early(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org, _pid, _bob = await _acme(client, client_for)
    await client.delete("/orgs/acme")
    ops = await _ops(client_for)
    r = await ops.post(
        f"/admin/organizations/{org}/deletion/execute", json={"reason": "customer asked"}
    )
    assert r.status_code == 200, r.text
    async with session_factory() as session:
        row = await session.get(Organization, uuid.UUID(org))
        assert row is not None and row.deleted_at is not None


async def test_operator_cannot_execute_without_a_request(
    client: AsyncClient, client_for: ClientFor
) -> None:
    org, _pid, _bob = await _acme(client, client_for)
    ops = await _ops(client_for)
    r = await ops.post(f"/admin/organizations/{org}/deletion/execute", json={"reason": "x"})
    assert r.status_code == 409


async def test_grace_period_default_is_configurable(
    client: AsyncClient, client_for: ClientFor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("BUILDER_ORG_DELETION_GRACE_DAYS", "14")
    get_settings.cache_clear()
    await _acme(client, client_for)
    body = (await client.delete("/orgs/acme")).json()
    scheduled = datetime.fromisoformat(body["deletion_scheduled_for"])
    assert scheduled - datetime.now(UTC) > timedelta(days=13)
    get_settings.cache_clear()
