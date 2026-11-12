"""CP-5V: GET/POST /admin/operations, admin org usage limits, project search reindex."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_security as sec
from app.jobs import report_scheduler
from app.models.enums import PlatformRole
from app.models.metrics import Report
from app.models.platform import AuditLog
from app.services import ops_service
from app.services.ops_service import record_heartbeat
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor
from tests.api.test_search_api import seeded

Factory = async_sessionmaker[AsyncSession]


async def _admin(client_for: ClientFor, role: PlatformRole = PlatformRole.platform_admin) -> AsyncClient:
    email = "ops@example.com" if role == PlatformRole.platform_admin else "support@example.com"
    return await client_for(email, role, audience=sec.AUDIENCE_ADMIN)


async def _org(client: AsyncClient) -> str:
    return (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()["id"]


# -- GET /admin/operations ---------------------------------------------------------------------


async def test_operations_overview_shape_and_no_secrets(client_for: ClientFor) -> None:
    ops = await _admin(client_for)
    r = await ops.get("/admin/operations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "generated_at", "scheduler", "idle_workspaces", "reports", "usage_defaults", "key_provider", "golive",
    }
    assert {j["job"] for j in body["scheduler"]["jobs"]} >= {"reports", "idle_sweep"}
    assert body["idle_workspaces"]["ttl_days"] == 14
    assert set(body["reports"]) == {"enabled_schedules", "disabled_schedules", "last_run_at", "next_run_at"}
    assert {"imports.rows", "workspaces.active"} <= {m["metric"] for m in body["usage_defaults"]}
    kp = body["key_provider"]
    assert set(kp) == {"kind", "healthy", "active_key_id", "key_count", "error"} and kp["healthy"] is True
    assert "path" not in kp and "command" not in kp
    assert all(c["status"] in ("pass", "fail", "warn", "skipped") for c in body["golive"]["checks"])


async def test_support_may_read_but_not_run_golive_and_customers_are_refused(client_for: ClientFor) -> None:
    support = await _admin(client_for, PlatformRole.platform_support)
    assert (await support.get("/admin/operations")).status_code == 200
    assert (await support.post("/admin/operations/golive")).status_code == 403
    customer = await client_for("cust@example.com")  # customer audience token
    assert (await customer.get("/admin/operations")).status_code in (401, 403)
    assert (await customer.post("/admin/operations/golive")).status_code in (401, 403)


async def test_heartbeat_is_written_by_the_job_and_shown(
    client_for: ClientFor, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report_scheduler, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(ops_service, "get_session_factory", lambda: session_factory)
    assert await report_scheduler.run_once() == 0
    await record_heartbeat("idle_sweep", False, "RuntimeError", 3600)
    ops = await _admin(client_for)
    jobs = {j["job"]: j for j in (await ops.get("/admin/operations")).json()["scheduler"]["jobs"]}
    assert jobs["reports"]["last_status"] == "ok" and jobs["reports"]["stale"] is False
    assert jobs["reports"]["interval_seconds"] == 60 and jobs["reports"]["next_expected_at"] is not None
    assert jobs["idle_sweep"]["last_status"] == "failed" and jobs["idle_sweep"]["last_error"] == "RuntimeError"
    assert jobs["idle_sweep"]["runs"] == 1


async def test_report_schedule_status_counts(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    pid = await make_project(client, "Rep")
    async with session_factory() as db:
        db.add(Report(project_id=uuid.UUID(pid), name="r1", schedule="0 9 * * *", timezone="UTC", enabled=True))
        db.add(Report(project_id=uuid.UUID(pid), name="r2", schedule="0 9 * * *", timezone="UTC", enabled=False))
        await db.commit()
    ops = await _admin(client_for)
    rep = (await ops.get("/admin/operations")).json()["reports"]
    assert rep["enabled_schedules"] == 1 and rep["disabled_schedules"] == 1
    assert datetime.fromisoformat(rep["next_run_at"]) > datetime.now(UTC)


async def test_golive_runs_in_process_with_reasons(client_for: ClientFor) -> None:
    ops = await _admin(client_for)
    r = await ops.post("/admin/operations/golive")
    assert r.status_code == 200, r.text
    body = r.json()
    by = {c["check"]: c for c in body["checks"]}
    assert by["P2 firewall"]["status"] == "skipped" and "root" in by["P2 firewall"]["detail"]
    assert by["P1 runner reachable"]["status"] == "skipped"
    assert by["P6 key provider"]["status"] == "pass"
    assert by["P1 runner configured"]["status"] == "fail"  # no runner in the test settings
    assert body["ok"] is False and body["failed"] >= 1
    assert body["passed"] + body["failed"] + body["warnings"] + body["skipped"] == len(body["checks"])
    assert "secret" not in r.text.lower()


# -- admin org usage -----------------------------------------------------------------------------


async def test_admin_reads_and_edits_org_usage_limits_by_id_and_slug(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org = await _org(client)
    ops = await _admin(client_for)
    usage = await ops.get("/admin/organizations/acme/usage")
    assert usage.status_code == 200
    by = {m["metric"]: m for m in usage.json()["metrics"]}
    assert by["imports.rows"]["limit"] == 50_000

    put = await ops.put("/admin/organizations/acme/usage/limits/imports.rows", json={"limit_value": 7})
    assert put.status_code == 200, put.text
    assert {m["metric"]: m for m in put.json()["metrics"]}["imports.rows"]["limit"] == 7
    by_id = (await ops.get(f"/admin/organizations/{org}/usage")).json()["metrics"]
    assert {m["metric"]: m for m in by_id}["imports.rows"]["limit"] == 7
    # the owner-facing route sees the admin's override too
    owner = await client.get("/orgs/acme/usage")
    assert {m["metric"]: m for m in owner.json()["metrics"]}["imports.rows"]["limit"] == 7

    cleared = await ops.put(f"/admin/organizations/{org}/usage/limits/imports.rows", json={"limit_value": None})
    assert {m["metric"]: m for m in cleared.json()["metrics"]}["imports.rows"]["limit"] is None  # unlimited

    async with session_factory() as db:
        rows = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.usage.limit.set"))).scalars().all()
    assert len(rows) == 2 and rows[0].detail["metric"] == "imports.rows"
    assert {r.detail["limit_value"] for r in rows} == {7, None}


async def test_admin_usage_refusals(client: AsyncClient, client_for: ClientFor) -> None:
    await _org(client)
    ops = await _admin(client_for)
    assert (await ops.put("/admin/organizations/acme/usage/limits/nope", json={"limit_value": 1})).status_code in (400, 404, 422)
    assert (await ops.put("/admin/organizations/acme/usage/limits/imports.rows", json={"limit_value": -1})).status_code == 422
    assert (await ops.get("/admin/organizations/missing/usage")).status_code == 404
    support = await _admin(client_for, PlatformRole.platform_support)
    assert (await support.get("/admin/organizations/acme/usage")).status_code == 200
    assert (await support.put("/admin/organizations/acme/usage/limits/imports.rows", json={"limit_value": 1})).status_code == 403
    assert (await client.put("/admin/organizations/acme/usage/limits/imports.rows", json={"limit_value": 1})).status_code in (401, 403)
    assert (await client.get("/admin/organizations/acme/usage")).status_code in (401, 403)


# -- search reindex -----------------------------------------------------------------------------


async def test_search_reindex_reports_searchable_records_and_needs_editor(
    client_for: ClientFor,
) -> None:
    owner = await client_for("a@example.com")
    pid = await seeded(owner, row_rule=None)
    r = await owner.post(f"/projects/{pid}/search/reindex")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == pid and body["indexed"] == 3
    assert [(e["entity"], e["records"]) for e in body["entities"]] == [("Person", 3)]
    assert (await owner.post(f"/projects/{pid}/search/reindex")).json() == body  # idempotent
    outsider = await client_for("b@example.com")
    assert (await outsider.post(f"/projects/{pid}/search/reindex")).status_code in (403, 404)
    assert (await owner.post(f"/projects/{uuid.uuid4()}/search/reindex")).status_code in (403, 404)
