"""FX-1: DB-backed fixed-window limiter shared by workers; pre-auth IP check; console-key cap."""

from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api import previews as api
from app.config import Settings
from app.core.ratelimit import SlidingWindowLimiter
from app.core.shared_limiter import SharedLimiter
from app.exceptions import AppError
from app.services import preview_service as ps
from app.services.ai.platform_cap import PlatformCap
from app.services.requirements.service import RequirementsService


def _worker(engine: AsyncEngine) -> SharedLimiter:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return SharedLimiter(lambda: maker)


async def test_two_workers_share_one_count(engine: AsyncEngine) -> None:
    w1, w2 = _worker(engine), _worker(engine)
    assert await w1.hit("k", 3, 60) is None
    assert await w2.hit("k", 3, 60) is None
    assert await w1.hit("k", 3, 60) is None
    wait = await w2.hit("k", 3, 60)  # 4th across both workers
    assert wait is not None and 1 <= wait <= 60
    assert await w1.hit("other", 3, 60) is None  # keys are independent


async def test_expired_windows_are_pruned_and_count_restarts(engine: AsyncEngine) -> None:
    w = _worker(engine)
    assert await w.hit("p", 1, 60) is None
    assert await w.hit("p", 1, 60) is not None
    async with engine.begin() as conn:  # the window ended
        await conn.execute(text("UPDATE rate_windows SET expires_at = 1, window_start = 0"))
    assert await w.hit("p", 1, 60) is None  # pruned on read, fresh window
    async with engine.connect() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM rate_windows WHERE key='p'"))).scalar_one()
    assert n == 1
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE rate_windows SET expires_at = 1"))
    await w.prune()
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM rate_windows"))).scalar_one() == 0


async def test_database_failure_refuses_closed() -> None:
    def broken() -> object:
        raise RuntimeError("db down")

    with pytest.raises(AppError) as exc:
        await SharedLimiter(broken).hit("k", 1, 60)  # type: ignore[arg-type]
    assert exc.value.status_code == 503


async def test_intake_limits_are_shared_across_workers(engine: AsyncEngine) -> None:
    stub = SimpleNamespace(s=SimpleNamespace(bind=engine))
    # two workers: each has its OWN in-process limiter, the database count is common
    a, b = SlidingWindowLimiter(2, 3600), SlidingWindowLimiter(2, 3600)
    call = RequirementsService._limited
    assert await call(stub, "intake:user:u1", "u1", a) is None  # type: ignore[arg-type]
    assert await call(stub, "intake:user:u1", "u1", b) is None  # type: ignore[arg-type]
    assert await call(stub, "intake:user:u1", "u1", a) is not None  # type: ignore[arg-type]
    assert await call(stub, "intake:user:u1", "u1", b) is not None  # type: ignore[arg-type]


def _req(ip: str) -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=ip), headers={})


def test_pre_auth_ip_limit_is_per_address_and_cheap() -> None:
    s = Settings(environment="test", preview_ip_rate_per_minute=2)
    api._ip_limiter = None
    api._pre_auth_ip_check(_req("1.2.3.4"), s)  # type: ignore[arg-type]
    api._pre_auth_ip_check(_req("1.2.3.4"), s)  # type: ignore[arg-type]
    with pytest.raises(AppError) as exc:
        api._pre_auth_ip_check(_req("1.2.3.4"), s)  # type: ignore[arg-type]
    assert exc.value.status_code == 429
    api._pre_auth_ip_check(_req("5.6.7.8"), s)  # type: ignore[arg-type]
    api._ip_limiter = None


async def test_gate_refuses_a_flood_before_sweep_or_any_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(environment="test", preview_ip_rate_per_minute=1)
    monkeypatch.setattr(api, "get_settings", lambda: s)
    api._ip_limiter = None
    calls: list[str] = []
    monkeypatch.setattr(ps, "maybe_sweep", lambda: calls.append("sweep"))

    async def auth(*_a: object) -> object:
        calls.append("auth")
        raise AppError("unauthorized", "no", 401)

    monkeypatch.setattr(ps, "authenticate", auth)
    req = SimpleNamespace(client=SimpleNamespace(host="9.9.9.9"), headers={})
    import uuid

    with pytest.raises(AppError) as first:
        await api._gate(uuid.uuid4(), req)  # type: ignore[arg-type]
    assert first.value.status_code == 401 and calls == ["sweep", "auth"]
    calls.clear()
    with pytest.raises(AppError) as second:
        await api._gate(uuid.uuid4(), req)  # type: ignore[arg-type]
    assert second.value.status_code == 429 and calls == []  # nothing ran before the refusal
    api._ip_limiter = None


async def test_console_key_share_caps_and_unbounded_key_warns(
    engine: AsyncEngine, session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    key = SecretStr("not-a-real-key-" + "x" * 8)
    async with session_factory() as s:
        warn = await PlatformCap(s, Settings(environment="test", ai_api_key=key)).unbounded_key_warning()
        assert warn and "cap_override" in warn
        shared = Settings(environment="test", ai_api_key=key, ai_console_key_cap_micro_usd=1_000)
        assert await PlatformCap(s, shared).unbounded_key_warning() is None
        assert await PlatformCap(s, Settings(environment="test", ai_api_key=None)).unbounded_key_warning() is None
    async with session_factory() as s:
        cap = PlatformCap(s, shared)
        async with cap._maker() as inner:
            assert await cap._cap(inner) == 1_000  # min(4.5 USD config, 1000 share)
        await s.execute(
            text("UPDATE ai_platform_budget SET cap_override_micro_usd = 5 WHERE id = 1")
        )
        await s.commit()
        async with cap._maker() as inner:
            assert await cap._cap(inner) == 5
        assert (
            await PlatformCap(s, Settings(environment="test", ai_api_key=key)).unbounded_key_warning()
            is None
        )  # an admin override also bounds it
