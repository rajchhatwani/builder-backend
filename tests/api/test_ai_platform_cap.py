"""CP-E: platform-wide hard spend cap. A call that could pass the cap is refused BEFORE it is sent."""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.exceptions import AppError
from app.services.ai.base import (
    Completion,
    CompletionRequest,
    Message,
    ModelProvider,
    ProviderError,
    StreamEvent,
    TaskClass,
    Usage,
)
from app.services.ai.gateway import ModelGateway
from app.services.ai.platform_cap import PlatformCap

Factory = async_sessionmaker[AsyncSession]
# 1 USD per million input, 10 USD per million output: easy sums in micro-USD.
PRICES = {"claude-haiku-5-5": {"input": 1_000_000, "output": 10_000_000, "cache_read": 0, "cache_write": 1_000_000}}


class Scripted(ModelProvider):
    name = "scripted"

    def __init__(self, usage: Usage | None = None, error: ProviderError | None = None) -> None:
        self.calls = 0
        self.usage = usage or Usage(input_tokens=100, output_tokens=50)
        self.error = error

    async def complete(self, model: str, request: CompletionRequest) -> Completion:
        self.calls += 1
        if self.error:
            raise self.error
        return Completion(model=model, text="ok", tool_calls=[], usage=self.usage)

    async def stream(self, model: str, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        if self.error:
            raise self.error
        yield StreamEvent("done", completion=Completion(model, "ok", [], self.usage))


def _settings(cap: int | None) -> Settings:
    return Settings(ai_price_table=PRICES, ai_platform_cap_micro_usd=cap, ai_small_model="claude-haiku-5-5")


async def _org(client: AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.post("/orgs", json={"name": "Cap", "slug": "cap"})).json()["id"])


async def _status(factory: Factory, settings: Settings) -> dict[str, int | None]:
    async with factory() as s:
        return await PlatformCap(s, settings).status()


def _req(max_tokens: int = 1000) -> CompletionRequest:
    return CompletionRequest("sys", [Message("user", "hello")], max_tokens=max_tokens)


async def test_call_that_could_exceed_cap_is_refused_before_sending(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await _org(client)
    provider = Scripted()
    cfg = _settings(5_000)  # worst case of a 1000-token reply = 10_000 micro-USD
    async with session_factory() as s:
        with pytest.raises(AppError) as exc:
            await ModelGateway(s, cfg, lambda k: provider).complete(org, TaskClass.route, _req())
    assert exc.value.code == "ai_platform_cap" and exc.value.status_code == 402
    assert provider.calls == 0
    assert (await _status(session_factory, cfg))["spent"] == 0


async def test_actual_cost_settles_and_reservation_is_released(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await _org(client)
    cfg = _settings(1_000_000)
    async with session_factory() as s:
        await ModelGateway(s, cfg, lambda k: Scripted()).complete(org, TaskClass.route, _req())
        await s.commit()
    st = await _status(session_factory, cfg)
    assert st["reserved"] == 0 and st["spent"] == 100 * 1 + 50 * 10 == 600


async def test_spend_survives_across_calls_and_blocks_at_the_cap(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await _org(client)
    cfg = _settings(25_000)
    ok = 0
    async with session_factory() as s:
        gw = ModelGateway(s, cfg, lambda k: Scripted(Usage(100, 800)))
        for _ in range(10):
            try:
                await gw.complete(org, TaskClass.route, _req(max_tokens=1000))
                ok += 1
            except AppError as exc:
                assert exc.code == "ai_platform_cap"
                break
        await s.commit()
    st = await _status(session_factory, cfg)
    assert ok == 2 and st["spent"] == 16_200


async def test_fake_provider_is_not_counted(client: AsyncClient, session_factory: Factory) -> None:
    from app.services.ai.fake import FakeProvider

    org = await _org(client)
    cfg = _settings(1)  # a cap of 1 micro-USD would refuse any real call
    async with session_factory() as s:
        await ModelGateway(s, cfg, lambda k: FakeProvider()).complete(org, TaskClass.route, _req())
    assert (await _status(session_factory, cfg))["spent"] == 0


async def test_unknown_outcome_counts_worst_case_but_http_error_counts_nothing(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await _org(client)
    cfg = _settings(1_000_000)
    async with session_factory() as s:
        gw = ModelGateway(s, cfg, lambda k: Scripted(error=ProviderError("rate limited", 429)))
        with pytest.raises(AppError):
            await gw.complete(org, TaskClass.route, _req())
    assert (await _status(session_factory, cfg))["spent"] == 0
    async with session_factory() as s:
        gw = ModelGateway(s, cfg, lambda k: Scripted(error=ProviderError("timeout")))
        with pytest.raises(AppError):
            await gw.complete(org, TaskClass.route, _req())
    st = await _status(session_factory, cfg)
    assert st["spent"] and st["spent"] >= 10_000 and st["reserved"] == 0


async def test_stream_is_reserved_and_settled(client: AsyncClient, session_factory: Factory) -> None:
    org = await _org(client)
    cfg = _settings(1_000_000)
    async with session_factory() as s:
        async for _ in ModelGateway(s, cfg, lambda k: Scripted()).stream(org, TaskClass.route, _req()):
            pass
        await s.commit()
    assert (await _status(session_factory, cfg))["spent"] == 600


async def test_admin_override_can_only_lower_the_cap(client: AsyncClient, session_factory: Factory) -> None:
    org = await _org(client)
    await _status(session_factory, _settings(None))  # creates the singleton row
    async with session_factory() as s:
        await s.execute(text("UPDATE ai_platform_budget SET cap_override_micro_usd = 5000 WHERE id=1"))
        await s.commit()
    high = _settings(10_000_000)
    async with session_factory() as s:
        with pytest.raises(AppError):
            await ModelGateway(s, high, lambda k: Scripted()).complete(org, TaskClass.route, _req())
    assert (await _status(session_factory, high))["cap"] == 5000


async def test_platform_budget_endpoint(client: AsyncClient) -> None:
    await _org(client)
    r = await client.get("/orgs/cap/ai/platform-budget")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["spent_micro_usd"] == 0 and body["cap_micro_usd"] == 4_500_000
    assert body["remaining_micro_usd"] == 4_500_000


async def test_platform_key_only_for_listed_orgs(client: AsyncClient, session_factory: Factory) -> None:
    from pydantic import SecretStr

    org = await _org(client)  # the slug "cap" must NOT work; the ID does
    seen: list[str | None] = []

    def factory(key: str | None) -> Scripted:
        seen.append(key)
        return Scripted()

    pk = "sk_" "ant_platform_test_key_000000"
    for orgs in ([], ["cap", "other"], [str(org)]):
        cfg = Settings(
            ai_price_table=PRICES, ai_small_model="claude-haiku-5-5", ai_api_key=SecretStr(pk), ai_platform_key_orgs=orgs
        )
        async with session_factory() as s:
            await ModelGateway(s, cfg, factory).complete(org, TaskClass.route, _req())
    assert seen == [None, None, pk]
