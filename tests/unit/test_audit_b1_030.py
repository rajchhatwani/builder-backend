"""Audit B1-030: linear anchor check, idempotency key across periods, behaviour tests for F-0308/F-0312."""

import ast
import asyncio
import re
import time
import types
from datetime import date, datetime, timedelta
from typing import Any

from tests.unit.test_audit_b1_054 import _files, _raw


def _fn(source: str, names: set[str], env: dict[str, Any]) -> types.ModuleType:
    tree = ast.parse(source)
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name in names]
    keep += [n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in names]
    mod = types.ModuleType("x")
    mod.__dict__.update(env)
    exec(compile(ast.Module(body=keep, type_ignores=[]), "x", "exec"), mod.__dict__)  # noqa: S102
    return mod


def _supported_mod() -> types.ModuleType:
    source = _files(_raw())["app/ai/documents_service.py"]
    return _fn(source, {"_STRIP", "_normal", "_supported"}, {"re": re})


def test_f1034_supported_is_linear_and_still_exact() -> None:
    mod = _supported_mod()
    quote = " ".join(["a"] * 5000)
    started = time.monotonic()
    assert mod._supported("b", quote) is False
    assert mod._supported("a" * 5001, quote) is False
    assert mod._supported("aaa", quote) is True
    assert time.monotonic() - started < 2
    assert mod._supported("125", "total 1,250.00 usd") is False  # a fragment of one word
    assert mod._supported("1,250.00", "total 1,250.00 usd") is True
    assert mod._supported("Total 1,250.00", "total 1,250.00 usd") is True
    assert mod._supported("1250.00 usd", "total 1,250.00 usd") is True
    assert mod._supported("", "x") is False and mod._supported(",", "x") is False
    assert mod._supported("ab", "x a b y") is True and mod._supported("ab", "xa b y") is False


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self.rows)


def test_f1035_stale_reservation_of_an_earlier_period_is_released_for_the_key() -> None:
    import sqlalchemy as sa

    source = _files(_raw())["app/ai/service.py"]
    calls: list[tuple[str, Any]] = []

    async def lock_period(session: Any, tenant: Any, start: date) -> str:
        calls.append(("lock", start))
        return f"period-{start}"

    async def release(session: Any, tenant: Any, period: Any, now: datetime) -> None:
        calls.append(("release", period))

    class AiCall:
        caller_id = sa.column("caller_id")
        idempotency_key = sa.column("idempotency_key")
        status = sa.column("status")
        period_start = sa.column("period_start")
        created_at = sa.column("created_at")

    env = dict(
        _sa=sa, _t=__import__("typing"), AiCall=AiCall, AsyncSession=object, Tenant=object, date=date, datetime=datetime,
        timedelta=timedelta, _config=types.SimpleNamespace(STALE_RESERVATION_SECONDS=300),
        _scoped=lambda stmt, model, tenant: stmt, _lock_period=lock_period, _release_stale=release,
    )
    mod = _fn(source, {"_release_stale_other_periods"}, env)
    session = _Session([date(2026, 1, 31)])
    now = datetime(2026, 2, 1, 0, 10)
    asyncio.run(mod._release_stale_other_periods(session, None, "u1", "k1", date(2026, 2, 1), now))
    assert calls == [("lock", date(2026, 1, 31)), ("release", "period-2026-01-31")]
    text = str(session.statements[0])
    assert "status" in text and "idempotency_key" in text and "period_start !=" in text
    body = source[source.index("async def complete(") :]
    assert body.index("_release_stale_other_periods(") < body.index("AiCall.idempotency_key == body.idempotency_key")


def test_f1036_anonymous_callers_are_not_charged_quota_behaviour() -> None:
    source = _files(_raw("api_edge_orders"))["app/api_edge/guard.py"]
    charged: list[Any] = []

    class Quota:
        class StoreError(Exception): ...

        @staticmethod
        def matching(path: str, method: str) -> list[str]:
            return ["m"]

        @staticmethod
        async def charge(key: str, matched: Any) -> None:
            charged.append(key)

    env = dict(
        quota=Quota, logger=None, AppError=Exception, Request=object, EdgeState=object,
        caller=types.SimpleNamespace(Caller=object),
    )
    mod = _fn(source, {"_quota"}, env)
    request = types.SimpleNamespace(url=types.SimpleNamespace(path="/orders"), method="GET")
    anon = types.SimpleNamespace(authenticated=False, tenant_key="-")
    user = types.SimpleNamespace(authenticated=True, tenant_key="t1")
    asyncio.run(mod._quota(request, None, anon))
    assert charged == []
    asyncio.run(mod._quota(request, None, user))
    assert charged == ["t1"]
