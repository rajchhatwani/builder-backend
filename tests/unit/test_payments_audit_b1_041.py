"""B1-041: payments template error paths (reconcile broad-except, webhook verify_error, content-length, cancel)."""

import __future__
import ast
import asyncio
import types
from pathlib import Path
from typing import Any

import pytest

TPL = Path(__file__).resolve().parents[2] / "app/core/generator/features/payments/templates/app/payments"


class _Err(Exception):
    def __init__(self, *a: Any, code: str = "x", reason: str = "r") -> None:
        super().__init__(*a)
        self.code = code
        self.reason = reason


class _Logger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        return lambda *a, **k: self.calls.append((name, a, k))


def _load(rel: str, names: set[str], ns: dict[str, Any]) -> dict[str, Any]:
    tree = ast.parse((TPL / rel).read_text(encoding="utf-8"))
    body = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name in names]
    assert {n.name for n in body} == names
    mod = ast.Module(body=body, type_ignores=[])
    exec(compile(mod, rel, "exec", flags=__future__.annotations.compiler_flag), ns)  # noqa: S102
    return ns


class _Headers(dict):
    pass


class _Request:
    def __init__(self, headers: dict[str, str], chunks: list[bytes] | None = None) -> None:
        self.headers = headers
        self._chunks = chunks or []

    async def stream(self) -> Any:
        for c in self._chunks:
            yield c


def test_content_length_non_ascii_digit_is_rejected_not_crash() -> None:
    cfg = types.SimpleNamespace(WEBHOOK_MAX_BODY_BYTES=100)
    ns = _load("router.py.tpl", {"_read_capped_body"}, {"config": cfg})
    fn = ns["_read_capped_body"]
    assert asyncio.run(fn(_Request({"content-length": "٣"}))) is None  # Arabic-indic 3
    assert asyncio.run(fn(_Request({"content-length": "3"}, [b"abc"]))) == b"abc"
    assert asyncio.run(fn(_Request({"content-length": "101"}))) is None


def test_webhook_verify_unexpected_error_is_400_not_500() -> None:
    class Rejected(Exception):
        reason = "bad"

    class Resp:
        def __init__(self, content: Any, status_code: int = 200) -> None:
            self.content, self.status_code = content, status_code

    class Provider:
        def verify_webhook(self, body: bytes, headers: Any) -> Any:
            raise KeyError("boom")

    class _Router:
        def post(self, *a: Any, **k: Any) -> Any:
            return lambda f: f

    async def read(_r: Any) -> bytes:
        return b"{}"

    log = _Logger()
    ns = {
        "router": _Router(),
        "config": types.SimpleNamespace(PROVIDER="stripe"),
        "JSONResponse": Resp,
        "_GENERIC_REJECTION": {"code": "rejected"},
        "_ip_allowed": lambda r: True,
        "_read_capped_body": read,
        "get_provider": lambda: Provider(),
        "WebhookRejected": Rejected,
        "logger": log,
        "NotFoundError": _Err,
        "Request": object,
        "Response": object,
    }
    ns = _load("router.py.tpl", {"receive_webhook"}, ns)
    resp = asyncio.run(ns["receive_webhook"]("stripe", types.SimpleNamespace(headers={})))
    assert resp.status_code == 400
    assert any(c[2].get("reason") == "verify_error" for c in log.calls)


class _Session:
    def __init__(self) -> None:
        self.rollbacks = 0

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *a: Any) -> None:
        return None

    async def get(self, _m: Any, pid: Any) -> Any:
        return types.SimpleNamespace(
            provider_session_id="cs", provider_payment_intent_id=None, status="x", id=pid
        )

    async def rollback(self) -> None:
        self.rollbacks += 1


def test_reconcile_sync_continues_after_unexpected_error() -> None:
    log = _Logger()
    retrieved: list[str] = []

    class Provider:
        async def retrieve_checkout(self, sid: str) -> Any:
            retrieved.append(sid)
            if len(retrieved) == 1:
                raise RuntimeError("boom")
            return object()

    async def sync(*a: Any, **k: Any) -> None:
        return None

    ns = {
        "get_provider": lambda: Provider(),
        "session_factory": lambda: _Session(),
        "Payment": object,
        "service": types.SimpleNamespace(sync_payment_from_checkout=sync),
        "audit": types.SimpleNamespace(ACTOR_SYSTEM="system"),
        "state": types.SimpleNamespace(SUCCEEDED="succeeded"),
        "ProviderError": _Err,
        "logger": log,
    }
    ns = _load("reconcile.py.tpl", {"_sync"}, ns)
    counts = {"payments": 0, "errors": 0}
    asyncio.run(ns["_sync"](["a", "b"], counts))
    assert len(retrieved) == 2
    assert counts == {"payments": 2, "errors": 1}
    assert any(c[1] and c[1][0] == "reconcile_payment_error" for c in log.calls)


def test_cancel_retrieve_provider_rejected_is_conflict() -> None:
    class Rejected(Exception):
        pass

    class Unavailable(Exception):
        pass

    class Conflict(Exception):
        pass

    class Provider:
        async def expire_checkout(self, sid: str) -> Any:
            raise Rejected()

        async def retrieve_checkout(self, sid: str) -> Any:
            raise Rejected()

    payment = types.SimpleNamespace(
        id="p", created_by_id="u", status="requires_payment", provider_session_id="cs"
    )

    async def get_payment(*a: Any, **k: Any) -> Any:
        return payment

    ns = {
        "get_payment": get_payment,
        "has_role": lambda u, k: False,
        "state": types.SimpleNamespace(REQUIRES_PAYMENT="requires_payment"),
        "get_provider": lambda: Provider(),
        "ProviderRejected": Rejected,
        "ProviderUnavailable": Unavailable,
        "ConflictError": Conflict,
        "NotFoundError": _Err,
        "AppError": _Err,
    }
    ns = _load("service.py.tpl", {"cancel_payment"}, ns)
    user = types.SimpleNamespace(id="u")
    with pytest.raises(Conflict):
        asyncio.run(ns["cancel_payment"](object(), user, "p"))
