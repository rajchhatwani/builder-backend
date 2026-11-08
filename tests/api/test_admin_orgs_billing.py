"""Backend gaps A–C, section 3: operator console API (PLATFORM_SAAS_PLAN §7, §6.5, §7.1)."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_security as sec
from app.models.enums import PlatformRole
from app.models.platform import AuditLog, Subscription
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]


async def _admin(
    client_for: ClientFor, role: PlatformRole = PlatformRole.platform_admin
) -> AsyncClient:
    return await client_for("ops@example.com", role, audience=sec.AUDIENCE_ADMIN)


async def _acme_with_project(owner: AsyncClient) -> tuple[str, str]:
    org = (await owner.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()["id"]
    pid = (await owner.post("/projects", json={"name": "App", "organization_id": org})).json()["id"]
    return org, pid


async def _live_stripe(factory: Factory, org_id: str) -> None:
    async with factory() as session:
        sub = await session.get(Subscription, uuid.UUID(org_id))
        assert sub is not None
        sub.stripe_customer_id = "cus_1"
        sub.stripe_subscription_id = "sub_1"
        await session.commit()


# -- org detail ------------------------------------------------------------------------------


async def test_org_detail_members_and_projects(client: AsyncClient, client_for: ClientFor) -> None:
    org, _pid = await _acme_with_project(client)
    ops = await _admin(client_for)
    members = await ops.get(f"/admin/organizations/{org}/members")
    assert members.status_code == 200
    assert [m["email"] for m in members.json()] == ["primary@example.com"]
    projects = await ops.get(f"/admin/organizations/{org}/projects")
    assert projects.status_code == 200
    body = projects.json()
    assert [p["name"] for p in body] == ["App"]
    # §7.1: metadata only — no spec content of any kind.
    assert set(body[0]) <= {"id", "name", "slug", "created_at", "updated_at", "entity_count"}


async def test_org_row_has_billing_fields_mrr_and_activity(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org, _ = await _acme_with_project(client)
    await _live_stripe(session_factory, org)
    ops = await _admin(client_for)
    row = (await ops.get(f"/admin/organizations/{org}")).json()
    assert row["stripe_customer_id"] == "cus_1"
    assert row["stripe_subscription_id"] == "sub_1"
    assert row["mrr_cents"] == 2900  # team: $29 x 1 seat, billed through Stripe
    assert row["last_activity_at"] is not None
    listed = (await ops.get("/admin/organizations?q=acme")).json()["items"][0]
    assert listed["mrr_cents"] == 2900


async def test_mrr_is_zero_without_a_paid_subscription(
    client: AsyncClient, client_for: ClientFor
) -> None:
    org, _ = await _acme_with_project(client)
    ops = await _admin(client_for)
    assert (await ops.get(f"/admin/organizations/{org}")).json()["mrr_cents"] == 0


# -- manual plan change ---------------------------------------------------------------------


async def test_manual_plan_change_needs_a_reason_and_is_audited(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org, _ = await _acme_with_project(client)
    ops = await _admin(client_for)
    r = await ops.patch(f"/admin/organizations/{org}/plan", json={"plan_id": "business"})
    assert r.status_code == 422  # reason required (§6.5)
    r = await ops.patch(
        f"/admin/organizations/{org}/plan", json={"plan_id": "business", "reason": "sales deal"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan_id"] == "business"
    async with session_factory() as session:
        row = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "admin.org_plan_change")
            )
        ).scalar_one()
        assert row.detail["reason"] == "sales deal"


async def test_manual_plan_change_refused_for_stripe_managed_orgs(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    """The next Stripe webhook would silently undo it, so refuse and point to Stripe."""
    org, _ = await _acme_with_project(client)
    await _live_stripe(session_factory, org)
    ops = await _admin(client_for)
    r = await ops.patch(
        f"/admin/organizations/{org}/plan", json={"plan_id": "business", "reason": "x"}
    )
    assert r.status_code == 409
    assert r.json()["code"] == "stripe_managed"


# -- plans tab ------------------------------------------------------------------------------


async def test_plan_ids_are_validated(client_for: ClientFor) -> None:
    ops = await _admin(client_for)
    body = {"display_name": "X", "monthly_price_usd": 0}
    assert (await ops.put("/admin/plans/Bad Id!", json=body)).status_code == 422
    assert (await ops.put("/admin/plans/" + "a" * 41, json=body)).status_code == 422
    assert (await ops.put("/admin/plans/startup", json=body)).status_code == 200


async def test_plan_edit_audit_records_the_diff(
    client_for: ClientFor, session_factory: Factory
) -> None:
    ops = await _admin(client_for)
    plans = {p["id"]: p for p in (await ops.get("/admin/plans")).json()}
    team = {k: v for k, v in plans["team"].items() if k != "id"}
    team["max_seats"] = 7
    assert (await ops.put("/admin/plans/team", json=team)).status_code == 200
    async with session_factory() as session:
        row = (
            await session.execute(select(AuditLog).where(AuditLog.action == "admin.plan_update"))
        ).scalar_one()
        assert row.detail["changes"] == "max_seats: 5 -> 7"
        assert "affected_orgs" in row.detail
    # restore for other tests (plans are shared across the session)
    team["max_seats"] = 5
    await ops.put("/admin/plans/team", json=team)


# -- billing tab and insights -----------------------------------------------------------------


async def test_billing_tab_lists_subscriptions(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org, _ = await _acme_with_project(client)
    await _live_stripe(session_factory, org)
    ops = await _admin(client_for)
    r = await ops.get("/admin/subscriptions?status=active&q=acme")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["organization_slug"] == "acme"
    assert items[0]["stripe_subscription_id"] == "sub_1"
    assert (await ops.get("/admin/subscriptions?status=past_due&q=acme")).json()["total"] == 0


async def test_insights(client: AsyncClient, client_for: ClientFor) -> None:
    await _acme_with_project(client)
    ops = await _admin(client_for)
    r = await ops.get("/admin/insights")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_projects"] >= 1
    assert body["active_orgs_7d"] >= 1
    assert isinstance(body["signups_per_day"], list)
    assert {"day", "count"} <= set(body["signups_per_day"][-1])
    assert "denied_by_quota_7d" in body and "mcp_calls_24h" in body


async def test_support_staff_can_read_but_not_change(
    client_for: ClientFor, client: AsyncClient
) -> None:
    org, _ = await _acme_with_project(client)
    support = await _admin(client_for, PlatformRole.platform_support)
    assert (await support.get(f"/admin/organizations/{org}/members")).status_code == 200
    assert (await support.get("/admin/subscriptions")).status_code == 200
    r = await support.patch(
        f"/admin/organizations/{org}/plan", json={"plan_id": "business", "reason": "x"}
    )
    assert r.status_code == 403
