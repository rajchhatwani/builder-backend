"""B3-7 API tests: AI settings (BYO key), budget cap, cost ledger. (Registry tests: test_project_registry.py.)"""

import logging
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.exceptions import AppError
from app.models.ai_ledger import AiCostLedger, AiOrgSettings
from app.models.platform import AuditLog
from app.services.ai.base import CompletionRequest, Message, TaskClass
from app.services.ai.fake import FakeProvider
from app.services.ai.gateway import ModelGateway
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]
KEY = "sk_" "ant_api_test_9876543210zz"


async def _org(client: AsyncClient, slug: str = "acme") -> uuid.UUID:
    return uuid.UUID((await client.post("/orgs", json={"name": slug.title(), "slug": slug})).json()["id"])


async def _call(factory: Factory, org: uuid.UUID, task: TaskClass, **kw: object) -> None:
    provider = FakeProvider()
    async with factory() as s:
        gw = ModelGateway(s, Settings(), lambda key: provider)
        await gw.complete(
            org, task, CompletionRequest("sys", [Message("user", "hello")]), **kw  # type: ignore[arg-type]
        )
        await s.commit()


# -- settings / BYO key ---------------------------------------------------------------------


async def test_key_is_encrypted_and_never_returned_or_logged(
    client: AsyncClient, session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    org = await _org(client)
    with caplog.at_level(logging.DEBUG):
        r = await client.put(
            "/orgs/acme/ai/settings", json={"api_key": KEY, "monthly_budget_micro_usd": 50_000_000}
        )
        g = await client.get("/orgs/acme/ai/settings")
    assert r.status_code == 200, r.text
    for resp in (r, g):
        assert KEY not in resp.text
        assert resp.json() == {
            "has_api_key": True,
            "api_key_hint": KEY[-4:],
            "monthly_budget_micro_usd": 50_000_000,
            "approval_policy": None,
        }
    assert KEY not in caplog.text
    async with session_factory() as s:
        row = (await s.execute(select(AiOrgSettings))).scalar_one()
        assert row.organization_id == org and row.api_key_enc and KEY not in row.api_key_enc
        audit = (await s.execute(select(AuditLog).where(AuditLog.action == "ai.settings.update")))
        assert KEY not in str([a.detail for a in audit.scalars()])
    # the stored key round-trips for the gateway
    seen: list[str | None] = []

    def factory(key: str | None) -> FakeProvider:
        seen.append(key)
        return FakeProvider()

    async with session_factory() as s:
        await ModelGateway(s, Settings(), factory).complete(
            org, TaskClass.route, CompletionRequest("s", [Message("user", "x")])
        )
    assert seen == [KEY]
    cleared = await client.put("/orgs/acme/ai/settings", json={"clear_api_key": True})
    assert cleared.json()["has_api_key"] is False


async def test_missing_key_is_a_clear_409(client: AsyncClient, session_factory: Factory) -> None:
    org = await _org(client)
    async with session_factory() as s:
        with pytest.raises(AppError) as exc:
            await ModelGateway(s, Settings()).complete(
                org, TaskClass.route, CompletionRequest("s", [Message("user", "x")])
            )
    assert exc.value.code == "ai_key_missing"


async def test_short_key_rejected_and_not_echoed(client: AsyncClient) -> None:
    await _org(client)
    r = await client.put("/orgs/acme/ai/settings", json={"api_key": "short"})
    assert r.status_code == 422 and "short" not in r.json().get("message", "")


async def test_malformed_keys_rejected_and_short_keys_get_no_hint(
    client: AsyncClient, session_factory: Factory
) -> None:
    from app.services.ai.ledger import key_hint

    await _org(client)
    for bad in ("x" * 30, "sk-" + "a b" * 10, "sk_" "ant short1234", "sk-ab\ncdefghijklmnopqrstu"):
        r = await client.put("/orgs/acme/ai/settings", json={"api_key": bad})
        assert r.status_code == 422, bad
        assert bad not in r.text
    assert key_hint("sk-" + "a" * 16) is None  # 19 chars: below the hint threshold
    assert key_hint("sk-" + "a" * 17 + "wxyz") == "wxyz"
    ok = await client.put("/orgs/acme/ai/settings", json={"api_key": KEY})
    assert ok.status_code == 200 and ok.json()["api_key_hint"] == KEY[-4:]


async def test_member_cannot_read_or_write_ai_settings(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await _org(client)
    bob = await client_for("bob@example.com")
    inv = await client.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    await bob.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    for r in (
        await bob.get("/orgs/acme/ai/settings"),
        await bob.put("/orgs/acme/ai/settings", json={"api_key": KEY}),
        await bob.get("/orgs/acme/ai/cost"),
        await bob.get("/orgs/acme/ai/platform-budget"),  # S2-014: other tenants' activity
        await bob.get("/orgs/acme/registry/projects"),
    ):
        assert r.status_code == 403


async def test_admin_can_read_platform_budget(client: AsyncClient) -> None:
    await _org(client)
    assert (await client.get("/orgs/acme/ai/platform-budget")).status_code == 200


# -- ledger ---------------------------------------------------------------------------------


async def test_ledger_rows_match_usage_and_price_table(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await _org(client)
    pid = uuid.UUID(await make_project(client))
    run = uuid.uuid4()
    await _call(session_factory, org, TaskClass.route, project_id=pid, run_id=run)
    await _call(session_factory, org, TaskClass.code)
    body = (await client.get("/orgs/acme/ai/cost")).json()
    assert body["total"] == 2
    by_model = {i["model"]: i for i in body["items"]}
    assert set(by_model) == {"claude-haiku-5-5", "claude-sonnet-5-5"}
    small = by_model["claude-haiku-5-5"]
    assert small["run_id"] == str(run) and small["project_id"] == str(pid)
    # fake usage for these inputs: recompute the cost from the row's own token counts
    for item, (pin, pout, pcr, pcw) in (
        (small, (1_000_000, 5_000_000, 100_000, 1_250_000)),
        (by_model["claude-sonnet-5-5"], (3_000_000, 15_000_000, 300_000, 3_750_000)),
    ):
        raw = (
            item["input_tokens"] * pin
            + item["output_tokens"] * pout
            + item["cache_read_tokens"] * pcr
            + item["cache_write_tokens"] * pcw
        )
        assert item["cost_micro_usd"] == -(-raw // 1_000_000)
    assert body["total_cost_micro_usd"] == sum(i["cost_micro_usd"] for i in body["items"])
    assert body["month_cost_micro_usd"] == body["total_cost_micro_usd"]


async def test_budget_cap_blocks_further_calls_and_records_nothing(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await _org(client)
    await _call(session_factory, org, TaskClass.code)
    spent = (await client.get("/orgs/acme/ai/cost")).json()["total_cost_micro_usd"]
    assert spent > 0
    await client.put("/orgs/acme/ai/settings", json={"monthly_budget_micro_usd": spent})
    with pytest.raises(AppError) as exc:
        await _call(session_factory, org, TaskClass.code)
    assert exc.value.status_code == 402 and exc.value.code == "ai_budget_exceeded"
    assert (await client.get("/orgs/acme/ai/cost")).json()["total"] == 1
    await client.put("/orgs/acme/ai/settings", json={"clear_budget": True})
    await _call(session_factory, org, TaskClass.code)
    assert (await client.get("/orgs/acme/ai/cost")).json()["total"] == 2


async def test_cross_org_ledger_read_refused_and_isolated(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org_a = await _org(client, "acme")
    await _call(session_factory, org_a, TaskClass.code)
    eve = await client_for("eve@example.com")
    await eve.post("/orgs", json={"name": "Evil", "slug": "evil"})
    # Eve is not a member of acme: same answer as "does not exist"
    for path in ("/orgs/acme/ai/cost", "/orgs/acme/ai/settings"):
        assert (await eve.get(path)).status_code == 404
    assert (await eve.put("/orgs/acme/ai/settings", json={"api_key": KEY})).status_code == 404
    own = (await eve.get("/orgs/evil/ai/cost")).json()
    assert own["total"] == 0 and own["items"] == []
    async with session_factory() as s:
        assert len((await s.execute(select(AiCostLedger))).scalars().all()) == 1
