"""Audit B1-042 (F-1164, F-1165, F-1166): the generated provider client / breaker and the search candidate loop
are exec'd from their templates with stubbed collaborators (no database, no network)."""

import asyncio
import sys
import types
import uuid
from pathlib import Path
from typing import Any

import pytest

FEATURES = Path(__file__).resolve().parents[2] / "app" / "core" / "generator" / "features"
PROV = FEATURES / "providers" / "templates" / "app" / "providers"
SEARCH = FEATURES / "search" / "templates" / "app" / "search" / "service.py.tpl"


def _module(name: str, source: str, **extra: Any) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__.update(extra)
    exec(compile(source, name, "exec"), mod.__dict__)  # noqa: S102 - our own generated template
    return mod


class _Defs:
    BREAKER_FAILURES = 3
    BREAKER_RESET_SECONDS = 30.0
    TIMEOUT_SECONDS = 5.0
    MAX_ATTEMPTS = 3


class _Adapter:
    name = "emulator"

    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.calls = 0

    async def call(self, request: Any, credentials: Any) -> str:
        self.calls += 1
        step = self.script.pop(0) if self.script else "ok"
        if isinstance(step, BaseException):
            raise step
        if step == "hang":
            await asyncio.sleep(3600)
        return step


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    from pydantic import BaseModel

    pkg = types.ModuleType("app.providers")
    pkg.__path__ = []  # type: ignore[attr-defined]
    errors = _module("app.providers.errors", (PROV / "errors.py.tpl").read_text(encoding="utf-8"))
    breaker = _module("app.providers.breaker", (PROV / "breaker.py.tpl").read_text(encoding="utf-8"))
    breaker.reset_all()

    class Req(BaseModel):
        x: int = 1

    holder: dict[str, Any] = {}

    class Registry:
        @staticmethod
        def allowed(kind: str) -> list[str]:
            return ["emulator"]

        @staticmethod
        def adapter(kind: str, name: str) -> Any:
            return holder["adapter"]

    class Config:
        is_test = staticmethod(lambda: True)
        is_production = staticmethod(lambda: False)

    class Log:
        log = staticmethod(lambda *a, **k: None)
        warn = staticmethod(lambda *a, **k: None)
        shape = staticmethod(lambda r: {})

    schemas = types.SimpleNamespace(REQUESTS={"payments": Req, "email": Req}, HealthStatus=object)
    base = types.SimpleNamespace(Credentials=object, ProviderAdapter=object)
    parts = {
        "config": Config, "definitions": _Defs, "logsafe": Log, "registry": Registry,
        "vault": types.SimpleNamespace(), "errors": errors, "breaker": breaker,
        "schemas": schemas, "base": base,
    }
    for key, value in parts.items():
        setattr(pkg, key, value)
        monkeypatch.setitem(sys.modules, f"app.providers.{key}", value if isinstance(value, types.ModuleType) else types.ModuleType(key))
    sys.modules["app.providers.schemas"].__dict__.update(vars(schemas))
    sys.modules["app.providers.base"].__dict__.update(vars(base))
    monkeypatch.setitem(sys.modules, "app.providers", pkg)
    monkeypatch.setattr(_Defs, "MAX_ATTEMPTS", 3)
    monkeypatch.setattr(_Defs, "TIMEOUT_SECONDS", 5.0)
    source = (PROV / "client.py.tpl").read_text(encoding="utf-8")
    mod = _module("app.providers.client", source)
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    mod.sleep = fake_sleep
    return types.SimpleNamespace(mod=mod, errors=errors, breaker=breaker, holder=holder, Req=Req, waits=waits)


async def _call(c: Any, kind: str = "payments") -> Any:
    return await c.mod.call_provider(None, uuid.uuid4(), kind, c.Req())


async def test_f1164_payments_is_not_repeated_after_a_timeout_or_5xx(client: Any) -> None:
    e = client.errors
    for failure in (e.ProviderTimeout("t"), e.Retryable("5xx")):
        client.holder["adapter"] = adapter = _Adapter([failure, failure, "ok"])
        with pytest.raises(type(failure)):
            await _call(client, "payments")
        assert adapter.calls == 1 and client.waits == []


async def test_f1164_payments_rate_limit_and_other_kinds_are_still_retried(client: Any) -> None:
    e = client.errors
    client.holder["adapter"] = adapter = _Adapter([e.RateLimited("slow", retry_after=2.0), "ok"])
    assert await _call(client, "payments") == "ok"
    assert adapter.calls == 2 and client.waits == [2.0]
    client.waits.clear()
    client.holder["adapter"] = adapter = _Adapter([e.Retryable("x"), "ok"])
    assert await _call(client, "email") == "ok"
    assert adapter.calls == 2


async def test_f1165_cancelled_probe_frees_the_half_open_slot(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(client.breaker.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(_Defs, "MAX_ATTEMPTS", 1)
    e = client.errors
    tenant = uuid.uuid4()
    client.holder["adapter"] = _Adapter([e.Retryable("x")] * 3)
    for _ in range(3):
        with pytest.raises(e.Retryable):
            await client.mod.call_provider(None, tenant, "email", client.Req())
    with pytest.raises(e.CircuitOpen):
        await client.mod.call_provider(None, tenant, "email", client.Req())
    now[0] += 31  # half-open: the probe hangs and its task is cancelled
    client.holder["adapter"] = hung = _Adapter(["hang"])
    task = asyncio.ensure_future(client.mod.call_provider(None, tenant, "email", client.Req()))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert hung.calls == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client.holder["adapter"] = after = _Adapter(["ok"])
    assert await client.mod.call_provider(None, tenant, "email", client.Req()) == "ok"
    assert after.calls == 1  # the next caller reached the adapter: the slot was freed


def test_f1165_a_lost_probe_expires_after_reset_seconds() -> None:
    breaker = _module("breaker_t", (PROV / "breaker.py.tpl").read_text(encoding="utf-8"))
    now = [0.0]
    b = breaker.CircuitBreaker(1, 10.0, clock=lambda: now[0])
    b.failure()
    now[0] = 11.0
    assert b.allow() and not b.allow()  # probe in flight, never reports
    now[0] = 15.0
    assert not b.allow()  # still within reset_seconds of the probe
    now[0] = 22.0
    assert b.allow()  # lost probe expired: another may try
    b.abandon()
    assert b.allow()  # abandon frees the slot at once


class _Repo:
    model = type("Person", (), {})
    searchable = ("name",)


async def test_f1166_search_widens_candidates_until_a_full_page_survives_the_scope() -> None:
    src = SEARCH.read_text(encoding="utf-8")
    ns: dict[str, Any] = {}

    class Unavailable(Exception):
        pass

    requested: list[int] = []
    mine = [str(uuid.uuid4()) for _ in range(3)]
    foreign = [str(uuid.uuid4()) for _ in range(200)]
    ranked = foreign + mine  # the caller's rows rank below 5 * limit foreign candidates

    class Adapter:
        async def query_ids(self, model: str, q: str, fields: Any, size: int) -> list[str]:
            requested.append(size)
            return ranked[:size]

    import ast

    tree = ast.parse(src)
    wanted = {"_indexed", "_visible"}
    body = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in wanted]
    assert {n.name for n in body} == wanted
    ns.update(
        uuid=uuid, Any=Any, SearchUnavailable=Unavailable, AppError=Exception, get_adapter=lambda: Adapter(),
        _CANDIDATES_PER_HIT=5, _CANDIDATES_MAX=2000, Repository=type("Repository", (), {"__class_getitem__": classmethod(lambda c, i: c)}),
    )
    mine_ids = {uuid.UUID(m) for m in mine}

    async def visible(repo: Any, raw: list[str], conditions: list[Any]) -> list[Any]:
        return [uuid.UUID(v) for v in dict.fromkeys(raw) if uuid.UUID(v) in mine_ids]

    mod = ast.Module(body=[n for n in body if n.name == "_indexed"], type_ignores=[])
    ns["_visible"] = visible
    exec(compile(ast.fix_missing_locations(mod), "svc", "exec"), ns)  # noqa: S102
    rows, total = await ns["_indexed"](_Repo, "q", 3, ("name",), [])
    assert [str(r) for r in rows] == mine and total == 3  # a full page despite 200 foreign hits ranking first
    assert requested == [15, 60, 240]  # x4 per round, stopped once the engine had nothing more

    # termination: the engine always fills the window and nothing is visible -> bounded by _CANDIDATES_MAX
    requested.clear()
    ranked[:] = [str(uuid.uuid4()) for _ in range(5000)]
    rows, total = await ns["_indexed"](_Repo, "q", 3, ("name",), [])
    assert rows == [] and total == 0
    assert requested == [15, 60, 240, 960, 2000] and max(requested) <= 2000
