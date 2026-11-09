"""CP-4B WP-A: B-009 ledger step_key + after_settle (one transaction), L2 stale reservation expiry."""

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.ai_ledger import AiCostLedger
from app.services.ai import platform_cap
from app.services.ai.base import (
    Completion,
    CompletionRequest,
    Message,
    ModelProvider,
    StreamEvent,
    TaskClass,
    Usage,
)
from app.services.ai.gateway import ModelGateway
from app.services.ai.platform_cap import PlatformCap

Factory = async_sessionmaker[AsyncSession]
PRICES = {"claude-haiku-5-5": {"input": 1_000_000, "output": 10_000_000, "cache_read": 0, "cache_write": 1_000_000}}


class P(ModelProvider):
    name = "p"

    async def complete(self, model: str, request: CompletionRequest) -> Completion:
        return Completion(model=model, text="ok", tool_calls=[], usage=Usage(100, 50))

    async def stream(self, model: str, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("done", completion=await self.complete(model, request))


def _cfg(cap: int | None = None, ttl: float = 1800.0) -> Settings:
    return Settings(
        ai_price_table=PRICES, ai_platform_cap_micro_usd=cap, ai_small_model="claude-haiku-5-5",
        ai_reservation_ttl_seconds=ttl,
    )


def _req() -> CompletionRequest:
    return CompletionRequest("sys", [Message("user", "hi")], max_tokens=100)


async def _org(client: AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.post("/orgs", json={"name": "Led", "slug": "led"})).json()["id"])


async def _rows(f: Factory, org: uuid.UUID) -> int:
    async with f() as s:
        return int((await s.execute(select(func.count()).select_from(AiCostLedger).where(AiCostLedger.organization_id == org))).scalar_one())


async def test_same_step_key_bills_once_and_after_settle_runs_each_time(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await _org(client)
    seen: list[int] = []

    async def hook(s: AsyncSession, comp: object) -> None:
        # the ledger row is already visible inside the same transaction
        seen.append(
            int((await s.execute(select(func.count()).select_from(AiCostLedger).where(AiCostLedger.organization_id == org))).scalar_one())
        )

    for _ in range(2):  # a retried step
        async with session_factory() as s:
            await ModelGateway(s, _cfg(), lambda k: P()).complete(
                org, TaskClass.route, _req(), step_key="run1:3", after_settle=hook
            )
    assert await _rows(session_factory, org) == 1
    assert seen == [1, 1]
    async with session_factory() as s:  # a different step bills normally; no key bills normally
        gw = ModelGateway(s, _cfg(), lambda k: P())
        await gw.complete(org, TaskClass.route, _req(), step_key="run1:4")
        await gw.complete(org, TaskClass.route, _req())
    assert await _rows(session_factory, org) == 3


async def test_failing_after_settle_rolls_the_ledger_row_back(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await _org(client)

    async def boom(s: AsyncSession, comp: object) -> None:
        raise RuntimeError("step write failed")

    async with session_factory() as s:
        with pytest.raises(RuntimeError):
            await ModelGateway(s, _cfg(), lambda k: P()).complete(
                org, TaskClass.route, _req(), step_key="run2:1", after_settle=boom
            )
    assert await _rows(session_factory, org) == 0  # spend and step commit together or not at all


async def test_unique_index_rejects_a_duplicate_key(client: AsyncClient, session_factory: Factory) -> None:
    org = await _org(client)
    async with session_factory() as s:
        for _ in range(2):
            s.add(AiCostLedger(organization_id=org, model="m", task_class="t", input_tokens=1,
                               output_tokens=1, cost_micro_usd=1, step_key="k:1"))
        with pytest.raises(Exception, match="uq_ai_cost_ledger_step_key"):
            await s.commit()


async def test_default_reservation_expiry_is_thirty_minutes_and_stale_hold_is_freed(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert Settings().ai_reservation_ttl_seconds == 1800.0
    cfg = _cfg(cap=100_000)
    async with session_factory() as s:
        cap = PlatformCap(s, cfg)
        r = await cap.reserve("claude-haiku-5-5", _req())  # the process "crashes" here
        assert (await cap.status())["reserved"] == r.micro_usd
        t0 = platform_cap.now()
        monkeypatch.setattr(platform_cap, "now", lambda: t0 + timedelta(minutes=29))
        assert (await cap.status())["reserved"] == r.micro_usd  # still held inside the lease
        monkeypatch.setattr(platform_cap, "now", lambda: t0 + timedelta(minutes=31))
        await cap.reserve("claude-haiku-5-5", _req())  # the next reserve sweeps the stale hold
        st = await cap.status()
        assert st["reserved"] < 2 * r.micro_usd and st["reserved"] == r.micro_usd
    async with session_factory() as s:
        await s.execute(text("UPDATE ai_platform_budget SET reserved_micro_usd=0"))
        await s.execute(text("DELETE FROM ai_spend_reservations"))
        await s.commit()
