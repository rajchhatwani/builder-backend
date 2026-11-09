"""B4-5 usage metering: atomic quotas, refusal records, idempotency, limits API, workspace quota."""

import asyncio
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.exceptions import AppError
from app.models.usage import UsageEvent
from app.models.workspace import Workspace
from app.services import workspace_service
from app.services.usage_service import UsageService, consume_import_rows
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]


async def _org(client: AsyncClient, slug: str = "acme") -> tuple[uuid.UUID, str]:
    r = await client.post("/orgs", json={"name": slug.title(), "slug": slug})
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"]), slug


async def _limit(client: AsyncClient, slug: str, metric: str, value: int | None) -> None:
    r = await client.put(f"/orgs/{slug}/usage/limits/{metric}", json={"limit_value": value})
    assert r.status_code == 200, r.text


async def _consume(factory: Factory, org: uuid.UUID, metric: str, n: int = 1, **kw: object) -> int:
    async with factory() as s:
        used = await UsageService(s).consume(org, metric, n, **kw)  # type: ignore[arg-type]
        await s.commit()
        return used


async def _count(factory: Factory, org: uuid.UUID, outcome: str, metric: str = "previews.started") -> int:
    async with factory() as s:
        q = select(func.count()).select_from(UsageEvent).where(
            UsageEvent.organization_id == org,
            UsageEvent.metric == metric,
            UsageEvent.outcome == outcome,
        )
        return int((await s.execute(q)).scalar_one())


async def test_call_past_the_quota_is_refused_and_recorded(
    client: AsyncClient, session_factory: Factory
) -> None:
    org, slug = await _org(client)
    await _limit(client, slug, "previews.started", 3)
    for _ in range(3):
        await _consume(session_factory, org, "previews.started")
    with pytest.raises(AppError) as exc:
        await _consume(session_factory, org, "previews.started")
    assert exc.value.code == "quota_exceeded" and exc.value.status_code == 429
    d = exc.value.details[0]
    assert d["metric"] == "previews.started" and d["limit"] == 3 and d["used"] == 3 and d["period_end"]
    assert await _count(session_factory, org, "granted") == 3
    assert await _count(session_factory, org, "refused") == 1  # survives the refusal
    body = (await client.get(f"/orgs/{slug}/usage")).json()
    m = {x["metric"]: x for x in body["metrics"]}["previews.started"]
    assert m["used"] == 3 and m["limit"] == 3 and m["refused"] == 1


async def test_refusal_over_http_is_429_with_details(
    client: AsyncClient, session_factory: Factory
) -> None:
    org, slug = await _org(client)
    await _limit(client, slug, "imports.rows", 10)
    async with session_factory() as s:
        await consume_import_rows(s, org, None, 10)
        await s.commit()
    with pytest.raises(AppError) as exc:
        async with session_factory() as s:
            await consume_import_rows(s, org, None, 1)
    assert exc.value.code == "quota_exceeded"
    assert exc.value.details[0]["metric"] == "imports.rows"


async def test_a_single_charge_bigger_than_the_limit_is_refused(
    client: AsyncClient, session_factory: Factory
) -> None:
    org, slug = await _org(client)
    await _limit(client, slug, "imports.rows", 5)
    with pytest.raises(AppError) as exc:
        await _consume(session_factory, org, "imports.rows", 6)
    assert exc.value.code == "quota_exceeded"
    assert await _count(session_factory, org, "granted", "imports.rows") == 0
    assert await _consume(session_factory, org, "imports.rows", 5) == 5


async def test_parallel_consumes_never_exceed_the_quota(
    client: AsyncClient, session_factory: Factory
) -> None:
    org, slug = await _org(client)
    await _limit(client, slug, "previews.started", 5)

    async def one() -> bool:
        try:
            await _consume(session_factory, org, "previews.started")
            return True
        except AppError as exc:
            assert exc.code == "quota_exceeded"
            return False

    got = await asyncio.gather(*[one() for _ in range(8)])
    assert sum(got) == 5
    assert await _count(session_factory, org, "granted") == 5
    assert await _count(session_factory, org, "refused") == 3
    m = {x["metric"]: x for x in (await client.get(f"/orgs/{slug}/usage")).json()["metrics"]}
    assert m["previews.started"]["used"] == 5


async def test_totals_equal_granted_calls(client: AsyncClient, session_factory: Factory) -> None:
    org, slug = await _org(client)
    await _limit(client, slug, "imports.rows", None)  # unlimited
    for n in (3, 4, 5):
        await _consume(session_factory, org, "imports.rows", n)
    m = {x["metric"]: x for x in (await client.get(f"/orgs/{slug}/usage")).json()["metrics"]}
    assert m["imports.rows"]["used"] == 12 and m["imports.rows"]["limit"] is None
    page = (await client.get(f"/orgs/{slug}/usage/events?metric=imports.rows&limit=2")).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert [e["amount"] for e in page["items"]] == [5, 4]  # newest first
    all_ev = (await client.get(f"/orgs/{slug}/usage/events?metric=imports.rows")).json()["items"]
    assert sum(e["amount"] for e in all_ev if e["outcome"] == "granted") == 12


async def test_idempotency_key_counts_once(client: AsyncClient, session_factory: Factory) -> None:
    org, slug = await _org(client)
    await _limit(client, slug, "previews.started", 2)
    for _ in range(3):
        assert await _consume(session_factory, org, "previews.started", idempotency_key="k1") == 1
    assert await _count(session_factory, org, "granted") == 1
    assert await _consume(session_factory, org, "previews.started", idempotency_key="k2") == 2
    # the same key under another metric is its own charge
    assert await _consume(session_factory, org, "imports.batches", idempotency_key="k1") == 1


async def test_parallel_same_key_counts_once(client: AsyncClient, session_factory: Factory) -> None:
    org, _ = await _org(client)
    await asyncio.gather(
        *[_consume(session_factory, org, "previews.started", idempotency_key="same") for _ in range(6)]
    )
    async with session_factory() as s:
        used = await UsageService(s).consume(org, "previews.started", idempotency_key="same")
    assert used == 1 and await _count(session_factory, org, "granted") == 1


async def test_a_rolled_back_caller_is_not_charged(client: AsyncClient, session_factory: Factory) -> None:
    org, _ = await _org(client)
    async with session_factory() as s:
        await UsageService(s).consume(org, "previews.started")
        await s.rollback()
    assert await _consume(session_factory, org, "previews.started") == 1


async def test_period_counter_resets_with_the_period(client: AsyncClient, session_factory: Factory) -> None:
    org, slug = await _org(client)
    await _limit(client, slug, "previews.started", 1)
    day1 = datetime(2026, 11, 9, 10, tzinfo=UTC)
    async with session_factory() as s:
        await UsageService(s, now=day1).consume(org, "previews.started")
        await s.commit()
        with pytest.raises(AppError):
            await UsageService(s, now=day1 + timedelta(hours=1)).consume(org, "previews.started")
        assert await UsageService(s, now=day1 + timedelta(days=1)).consume(org, "previews.started") == 1
        await s.commit()


async def test_gauge_release_never_goes_below_zero(client: AsyncClient, session_factory: Factory) -> None:
    org, _ = await _org(client)
    await _consume(session_factory, org, "workspaces.active")
    async with session_factory() as s:
        svc = UsageService(s)
        assert await svc.release(org, "workspaces.active") == 0
        assert await svc.release(org, "workspaces.active") == 0
        with pytest.raises(AppError) as exc:
            await svc.release(org, "previews.started")
        assert exc.value.code == "not_a_gauge"
        await s.commit()


async def test_unknown_metric_is_refused(client: AsyncClient, session_factory: Factory) -> None:
    org, slug = await _org(client)
    with pytest.raises(AppError) as exc:
        await _consume(session_factory, org, "api.requests")
    assert exc.value.code == "unknown_metric"
    r = await client.put(f"/orgs/{slug}/usage/limits/api.requests", json={"limit_value": 1})
    assert r.status_code == 400


async def test_limit_override_owner_ok_member_forbidden(
    client: AsyncClient, client_for: ClientFor
) -> None:
    _, slug = await _org(client)
    bob = await client_for("bob@example.com")
    inv = await client.post(f"/orgs/{slug}/invitations", json={"email": "bob@example.com", "role": "member"})
    await bob.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    r = await client.put(f"/orgs/{slug}/usage/limits/imports.batches", json={"limit_value": 7})
    assert r.status_code == 200
    m = {x["metric"]: x for x in r.json()["metrics"]}
    assert m["imports.batches"]["limit"] == 7
    assert (await bob.put(f"/orgs/{slug}/usage/limits/imports.batches", json={"limit_value": 99})).status_code == 403
    assert (await bob.get(f"/orgs/{slug}/usage")).status_code == 200  # any member reads
    assert (await bob.get(f"/orgs/{slug}/usage/events")).status_code == 200
    cleared = await client.put(f"/orgs/{slug}/usage/limits/imports.batches", json={"limit_value": None})
    assert {x["metric"]: x for x in cleared.json()["metrics"]}["imports.batches"]["limit"] is None
    assert (await client.put(f"/orgs/{slug}/usage/limits/imports.batches", json={"limit_value": -1})).status_code == 422


async def test_other_orgs_cannot_read_usage(client: AsyncClient, client_for: ClientFor, session_factory: Factory) -> None:
    org, slug = await _org(client)
    await _consume(session_factory, org, "previews.started")
    eve = await client_for("eve@example.com")
    assert (await eve.get(f"/orgs/{slug}/usage")).status_code == 404
    assert (await eve.get(f"/orgs/{slug}/usage/events")).status_code == 404
    assert (await eve.put(f"/orgs/{slug}/usage/limits/imports.rows", json={"limit_value": 1})).status_code == 404


# -- FX-8: workspaces ---------------------------------------------------------------------------


@pytest.fixture
def ws_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str) -> Settings:
    s = Settings(
        environment="test",
        workspace_root=str(tmp_path / "ws"),
        workspace_db_admin_url=SecretStr(database_url),
    )
    monkeypatch.setattr(workspace_service, "get_settings", lambda: s)
    return s


async def _personal(client: AsyncClient) -> tuple[uuid.UUID, str]:
    body = (await client.get("/orgs")).json()
    orgs = body if isinstance(body, list) else body["items"]
    return uuid.UUID(orgs[0]["id"]), orgs[0]["slug"]


async def _gauge(client: AsyncClient, slug: str) -> int:
    m = {x["metric"]: x for x in (await client.get(f"/orgs/{slug}/usage")).json()["metrics"]}
    return int(m["workspaces.active"]["used"])


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


@needs_git
async def test_workspace_quota_refuses_at_limit_and_delete_releases(
    client: AsyncClient, ws_settings: Settings
) -> None:
    _, slug = await _personal(client)
    await _limit(client, slug, "workspaces.active", 1)
    pid = await make_project(client)
    base = f"/projects/{pid}/workspaces"
    first = await client.post(base, json={"name": "one"})
    assert first.status_code == 201, first.text
    assert await _gauge(client, slug) == 1
    refused = await client.post(base, json={"name": "two"})
    assert refused.status_code == 429 and refused.json()["code"] == "quota_exceeded"
    assert refused.json()["details"][0]["metric"] == "workspaces.active"
    assert len((await client.get(base)).json()) == 1  # nothing half-created
    events = (await client.get(f"/orgs/{slug}/usage/events?metric=workspaces.active")).json()
    assert [e["outcome"] for e in events["items"]].count("refused") == 1
    assert (await client.delete(f"{base}/{first.json()['id']}")).status_code == 200
    assert await _gauge(client, slug) == 0
    # deleting again must not release a second time
    await client.delete(f"{base}/{first.json()['id']}")
    assert await _gauge(client, slug) == 0
    assert (await client.post(base, json={"name": "three"})).status_code == 201
    assert await _gauge(client, slug) == 1


@needs_git
async def test_idle_ttl_sweep_removes_only_idle_workspaces(
    client: AsyncClient, ws_settings: Settings, session_factory: Factory
) -> None:
    _, slug = await _personal(client)
    pid = await make_project(client)
    base = f"/projects/{pid}/workspaces"
    old = (await client.post(base, json={"name": "old"})).json()
    fresh = (await client.post(base, json={"name": "fresh"})).json()
    assert await _gauge(client, slug) == 2
    async with session_factory() as s:
        await s.execute(
            text("UPDATE workspaces SET updated_at = :t WHERE id = :i"),
            {"t": datetime.now(UTC) - timedelta(days=30), "i": uuid.UUID(old["id"])},
        )
        await s.commit()
    async with session_factory() as s:
        done = await workspace_service.expire_idle_workspaces(
            s, datetime.now(UTC), timedelta(days=14), ws_settings
        )
    assert done == [uuid.UUID(old["id"])]
    async with session_factory() as s:
        states = {
            str(w.id): w.state for w in (await s.execute(select(Workspace))).scalars()
        }
    assert states[old["id"]] == "discarded" and states[fresh["id"]] == "active"
    assert await _gauge(client, slug) == 1
    async with session_factory() as s:  # a second sweep finds nothing
        assert await workspace_service.expire_idle_workspaces(
            s, datetime.now(UTC), timedelta(days=14), ws_settings
        ) == []
