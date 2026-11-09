"""B4-4: one metric definition, many consumers; scheduled reports fire each slot exactly once."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.metrics import ReportRun
from app.services.metrics_service import fire_due_reports
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

CSV = b"Ref,Amount,Status\nA1,10.10,paid\nA2,20.20,paid\nA3,0.30,open\n"
TOTAL = {
    "key": "total_amount", "label": "Total amount", "entity": "Order", "agg": "sum", "field": "amount",
}  # fmt: skip


async def project_with_orders(client: AsyncClient) -> str:
    pid = await make_project(client, "Shop")
    raw = {
        "spec_version": 1,
        "project": {"name": "Shop", "slug": "shop", "description": None, "db_engine": "postgres"},
        "entities": [
            {
                "name": "Order",
                "table_name": "orders",
                "plural_path": "orders",
                "options": {},
                "fields": [
                    {"name": "ref", "type": "string", "unique": True},
                    {"name": "amount", "type": "decimal"},
                    {"name": "status", "type": "string"},
                ],
            }
        ],
        "relations": [],
    }
    assert (await client.put(f"/projects/{pid}/spec", json=raw)).status_code == 200
    up = await client.post(
        f"/projects/{pid}/imports",
        files={"file": ("o.csv", CSV, "text/csv")},
        data={"entity": "Order"},
    )
    assert up.status_code == 201, up.text
    c = await client.post(f"/projects/{pid}/imports/{up.json()['batch_id']}/commit")
    assert c.status_code == 200 and c.json()["created"] == 3, c.text
    return pid


async def make_metric(client: AsyncClient, pid: str, **over: Any) -> Any:
    return await client.post(f"/projects/{pid}/metrics", json={"definition": {**TOTAL, **over}})


async def make_report(client: AsyncClient, pid: str, name: str, schedule: str, tz: str = "UTC") -> str:
    r = await client.post(
        f"/projects/{pid}/reports",
        json={"name": name, "metric_keys": ["total_amount"], "schedule": schedule, "timezone": tz},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def n_runs(sf: async_sessionmaker[AsyncSession], report_id: str) -> int:
    async with sf() as s:
        q = select(func.count()).select_from(ReportRun).where(ReportRun.report_id == report_id)
        return (await s.execute(q)).scalar_one()


async def test_one_definition_two_reports_same_value_and_scheduler_once(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await project_with_orders(client)
    created = await make_metric(client, pid)
    assert created.status_code == 201 and created.json()["version"] == 1, created.text
    live = (await client.get(f"/projects/{pid}/metrics/total_amount/value")).json()
    assert live["value"] == "30.6" and live["version"] == 1  # 10.10 + 20.20 + 0.30, exact

    r1 = await make_report(client, pid, "Daily", "0 6 * * *")
    r2 = await make_report(client, pid, "Hourly Berlin", "0 * * * *", "Europe/Berlin")
    for rid in (r1, r2):
        v = (await client.get(f"/projects/{pid}/reports/{rid}/value")).json()
        assert v["values"]["total_amount"] == {"value": "30.6", "version": 1}
        man = await client.post(f"/projects/{pid}/reports/{rid}/run")
        assert man.status_code == 200 and man.json()["status"] == "ok", man.text
        assert man.json()["values"]["total_amount"] == {"value": "30.6", "version": 1}

    # scheduler: the same `now` twice stores each slot once
    now = datetime.now(UTC) + timedelta(days=3, hours=1, minutes=5)
    async with session_factory() as s:
        assert await fire_due_reports(s, now) == 2
    async with session_factory() as s:
        assert await fire_due_reports(s, now) == 0
    runs1 = (await client.get(f"/projects/{pid}/reports/{r1}/runs")).json()
    scheduled = [x for x in runs1["items"] if x["scheduled_for"].endswith("06:00:00Z") or "T06:00:00" in x["scheduled_for"]]
    assert len(scheduled) == 1 and scheduled[0]["values"]["total_amount"]["value"] == "30.6"

    # six schedulers at once at a later time: exactly one more run each
    later = now + timedelta(days=2)

    async def one() -> int:
        async with session_factory() as s:
            return await fire_due_reports(s, later)

    fired = await asyncio.gather(*[one() for _ in range(6)])
    assert sum(fired) == 2, fired
    assert await n_runs(session_factory, r1) == 3 and await n_runs(session_factory, r2) == 3  # manual + 2

    # catch-up: a long gap stores only the latest slot, and a disabled report never fires
    put = await client.put(
        f"/projects/{pid}/reports/{r2}",
        json={"name": "Hourly Berlin", "metric_keys": ["total_amount"], "schedule": "0 * * * *",
              "timezone": "Europe/Berlin", "enabled": False},
    )  # fmt: skip
    assert put.status_code == 200
    way_later = later + timedelta(days=30)
    async with session_factory() as s:
        assert await fire_due_reports(s, way_later) == 1  # r1 only, one slot not thirty
    assert await n_runs(session_factory, r1) == 4 and await n_runs(session_factory, r2) == 3


async def test_changing_the_definition_changes_every_report(client: AsyncClient) -> None:
    pid = await project_with_orders(client)
    await make_metric(client, pid)
    r1 = await make_report(client, pid, "A", "0 6 * * *")
    r2 = await make_report(client, pid, "B", "30 7 * * 1")
    put = await client.put(
        f"/projects/{pid}/metrics/total_amount",
        json={"definition": {**TOTAL, "filter": [{"field": "status", "op": "eq", "value": "paid"}]}},
    )
    assert put.status_code == 200 and put.json()["version"] == 2, put.text
    for rid in (r1, r2):
        v = (await client.get(f"/projects/{pid}/reports/{rid}/value")).json()
        assert v["values"]["total_amount"] == {"value": "30.3", "version": 2}
        run = (await client.post(f"/projects/{pid}/reports/{rid}/run")).json()
        assert run["values"]["total_amount"] == {"value": "30.3", "version": 2}
    assert (await client.get(f"/projects/{pid}/metrics/total_amount/value")).json()["value"] == "30.3"
    # a metric a report uses cannot be deleted; an unused one can
    assert (await client.delete(f"/projects/{pid}/metrics/total_amount")).json()["code"] == "metric_in_use"
    await make_metric(client, pid, key="orders", agg="count", field=None, group_by="status")
    grouped = (await client.get(f"/projects/{pid}/metrics/orders/value")).json()
    assert grouped["value"] == 3 and grouped["groups"] == [
        {"key": "open", "value": 1}, {"key": "paid", "value": 2},
    ]  # fmt: skip
    assert (await client.delete(f"/projects/{pid}/metrics/orders")).status_code == 204


async def test_invalid_definitions_have_a_stable_code(client: AsyncClient) -> None:
    pid = await project_with_orders(client)
    bad: list[dict[str, Any]] = [
        {"agg": "sum", "field": "status"},
        {"agg": "median"},
        {"entity": "Nope"},
        {"filter": [{"field": "amount", "op": "gt", "value": "abc"}]},
        {"key": "Not Snake"},
        {"sql": "drop table x"},
    ]
    for over in bad:
        r = await make_metric(client, pid, **over)
        assert r.status_code == 422 and r.json()["code"] == "metric_invalid", (over, r.text)
    assert (await make_metric(client, pid)).status_code == 201
    dup = await make_metric(client, pid)
    assert dup.status_code == 409 and dup.json()["code"] == "metric_exists"
    r = await client.put(f"/projects/{pid}/metrics/total_amount", json={"definition": {**TOTAL, "agg": "sum", "field": "ref"}})
    assert r.json()["code"] == "metric_invalid"
    r = await client.put(f"/projects/{pid}/metrics/total_amount", json={"definition": {**TOTAL, "key": "other"}})
    assert r.json()["code"] == "metric_invalid"
    bad_report = await client.post(
        f"/projects/{pid}/reports",
        json={"name": "x", "metric_keys": ["total_amount"], "schedule": "* * *", "timezone": "UTC"},
    )
    assert bad_report.status_code == 422 and bad_report.json()["code"] == "report_invalid"
    unknown = await client.post(
        f"/projects/{pid}/reports",
        json={"name": "x", "metric_keys": ["ghost"], "schedule": "0 6 * * *"},
    )
    assert unknown.json()["code"] == "report_invalid"


async def test_roles_and_isolation(client: AsyncClient, client_for: ClientFor) -> None:
    pid = await project_with_orders(client)
    await make_metric(client, pid)
    rid = await make_report(client, pid, "Daily", "0 6 * * *")
    await add_to_project_org(pid, "vi@example.com")
    vi = await client_for("vi@example.com")
    await add_to_project_org(pid, "vi@example.com")
    assert (await client.post(f"/projects/{pid}/members", json={"email": "vi@example.com", "role": "viewer"})).status_code == 201
    assert (await vi.get(f"/projects/{pid}/metrics")).status_code == 200
    assert (await vi.get(f"/projects/{pid}/metrics/total_amount/value")).status_code == 200
    assert (await vi.get(f"/projects/{pid}/reports/{rid}/runs")).status_code == 200
    assert (await vi.get(f"/projects/{pid}/reports/{rid}/value")).status_code == 200
    assert (await make_metric(vi, pid, key="x")).status_code == 403
    assert (await vi.put(f"/projects/{pid}/metrics/total_amount", json={"definition": TOTAL})).status_code == 403
    assert (await vi.delete(f"/projects/{pid}/metrics/total_amount")).status_code == 403
    assert (await vi.post(f"/projects/{pid}/reports/{rid}/run")).status_code == 403
    assert (await vi.delete(f"/projects/{pid}/reports/{rid}")).status_code == 403
    # outsiders and other projects of the same owner see nothing
    eve = await client_for("eve@example.com")
    assert (await eve.get(f"/projects/{pid}/metrics")).status_code == 404
    other = await make_project(client, "Other")
    assert (await client.get(f"/projects/{other}/metrics/total_amount")).status_code == 404
    assert (await client.get(f"/projects/{other}/reports/{rid}")).status_code == 404
    assert (await client.post(f"/projects/{other}/reports/{rid}/run")).status_code == 404
    assert (await client.get(f"/projects/{other}/reports/{rid}/runs")).status_code == 404
    assert (await client.get(f"/projects/{other}/metrics")).json()["total"] == 0


async def test_manual_run_is_metered(client: AsyncClient) -> None:
    pid = await project_with_orders(client)
    await make_metric(client, pid)
    rid = await make_report(client, pid, "Daily", "0 6 * * *")
    slug = (await client.get("/orgs")).json()["items"][0]["slug"]
    r = await client.put(f"/orgs/{slug}/usage/limits/reports.runs", json={"limit_value": 1})
    assert r.status_code == 200, r.text
    assert (await client.post(f"/projects/{pid}/reports/{rid}/run")).status_code == 200
    await asyncio.sleep(1.1)  # a new second bucket, so it is a new run
    again = await client.post(f"/projects/{pid}/reports/{rid}/run")
    assert again.status_code == 429 and "quota_exceeded" in again.text
    assert (await client.get(f"/projects/{pid}/reports/{rid}/runs")).json()["total"] == 1
