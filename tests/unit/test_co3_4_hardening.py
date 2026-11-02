"""CO3-4: spec-write body cap, per-tenant effect budget, workflow NUL/cancel/resume (template-level), advisor."""

import asyncio
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.api.body_limit import SpecWriteLimit, is_spec_write

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ROOT / "app/core/generator/features"


def _load_budget() -> Any:
    path = FEATURES / "hooks/templates/app/platform_sdk/budget.py.tpl"
    spec = importlib.util.spec_from_loader("budget_tpl", loader=None)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


# --- body cap ---------------------------------------------------------------------------------


async def _call(app: Any, method: str, path: str, chunks: list[bytes], headers: list[tuple[bytes, bytes]] | None = None) -> tuple[int, bytes]:
    scope = {"type": "http", "method": method, "path": path, "headers": headers or []}
    queue = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)]
    out: dict[str, Any] = {"status": 0, "body": b""}

    async def receive() -> dict[str, Any]:
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
        else:
            out["body"] += message.get("body", b"")

    await app(scope, receive, send)
    return out["status"], out["body"]


def _echo_app() -> Any:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        body = b""
        while True:
            m = await receive()
            body += m.get("body", b"")
            if not m.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": str(len(body)).encode()})

    return app


def test_only_spec_writes_are_matched() -> None:
    assert is_spec_write("PUT", "/projects/abc/spec")
    assert is_spec_write("PUT", "/projects/abc/behavior/settings")
    assert not is_spec_write("GET", "/projects/abc/spec")
    assert not is_spec_write("PUT", "/projects/abc/spec/ops")
    assert not is_spec_write("POST", "/projects/abc/entities")


def test_oversize_chunked_spec_write_is_413_without_content_length() -> None:
    app = SpecWriteLimit(_echo_app(), max_bytes=100)
    status, body = asyncio.run(_call(app, "PUT", "/projects/p/spec", [b"x" * 60, b"x" * 60]))
    assert status == 413 and json.loads(body)["code"] == "payload_too_large"


def test_oversize_declared_length_is_413_and_a_lying_header_does_not_help() -> None:
    app = SpecWriteLimit(_echo_app(), max_bytes=100)
    status, _ = asyncio.run(_call(app, "PUT", "/projects/p/spec", [b"x"], [(b"content-length", b"500")]))
    assert status == 413
    status, _ = asyncio.run(_call(app, "PUT", "/projects/p/spec", [b"x" * 200], [(b"content-length", b"1")]))
    assert status == 413


def test_a_body_within_the_cap_is_replayed_intact_and_other_routes_are_untouched() -> None:
    app = SpecWriteLimit(_echo_app(), max_bytes=100)
    assert asyncio.run(_call(app, "PUT", "/projects/p/spec", [b"x" * 50, b"y" * 50])) == (200, b"100")
    assert asyncio.run(_call(app, "POST", "/projects/p/entities", [b"x" * 500])) == (200, b"500")


# --- per-tenant effect budget -----------------------------------------------------------------


def test_effect_rate_is_per_tenant_across_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    b = _load_budget()
    limits = b.EffectLimits(frozenset({"email"}), 10.0, 100, 1000, 2)
    ledger = b.Ledger(clock=lambda: 0.0)
    for hook in ("h1", "h2"):  # two hooks of tenant A share one allowance
        ledger.charge(hook, limits, {}, "email", 1, 0.0, "A")
    with pytest.raises(b.OverBudget) as over:
        ledger.charge("h3", limits, {}, "email", 1, 0.0, "A")
    assert over.value.code == "rate"
    ledger.charge("h1", limits, {}, "email", 1, 0.0, "B")  # tenant B is unaffected


def test_replica_count_divides_the_per_process_share(monkeypatch: pytest.MonkeyPatch) -> None:
    b = _load_budget()
    limits = b.EffectLimits(frozenset({"email"}), 10.0, 100, 1000, 10)
    monkeypatch.setenv("EFFECT_REPLICAS", "5")
    ledger = b.Ledger(clock=lambda: 0.0)
    ledger.charge("h", limits, {}, "email", 1, 0.0, "A")
    ledger.charge("h", limits, {}, "email", 1, 0.0, "A")
    with pytest.raises(b.OverBudget):
        ledger.charge("h", limits, {}, "email", 1, 0.0, "A")  # ceil(10/5) = 2
    monkeypatch.setenv("EFFECT_REPLICAS", "garbage")
    assert b.replicas() == 1


# --- workflow template guards (the behaviour itself runs in the generated project's tests) -------


def test_workflow_engine_template_refuses_nul_and_settles_a_cancel_while_waiting() -> None:
    engine = (FEATURES / "workflows/templates/app/workflows/engine.py.tpl").read_text()
    assert '"\\x00" in dedupe_key' in engine
    assert "async def resume_undo" in engine
    assert re.search(r"elif row\.status == RUNNING and row\.lease_token is None", engine)
    router = (FEATURES / "workflows/templates/app/workflows/router.py.tpl").read_text()
    assert "/runs/{run_id}/resume-undo" in router and "_no_nul" in router
