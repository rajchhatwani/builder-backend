"""Run fixed eval tasks through the real RunDriver with a scripted model (deterministic mode).

A task is driven the way a person would drive it over the API (create project and draft workspace,
create run, resume, decide approvals), so the real tools, approvals and gates are what is measured.
Only the model is replaced by the task's transcript. `live` mode (a real provider) is not wired here.
"""

import json
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.ai_ledger import AiCostLedger
from app.services.agent_eval.report import TaskResult
from app.services.ai.base import (
    Completion,
    CompletionRequest,
    ModelProvider,
    StreamEvent,
    ToolCall,
    Usage,
)

TASKS_DIR = Path(__file__).resolve().parents[3] / "tests" / "agent_eval" / "tasks"
BASELINE = Path(__file__).resolve().parents[3] / "tests" / "agent_eval" / "baseline.json"
MAX_ROUNDS = 12


class EvalError(Exception):
    pass


def eval_toolbox() -> Any:
    """The real toolbox, plus a refresh of the run row after each tool call.

    A failing spec op rolls the session back, which expires the loaded AiRun; the driver then reads
    `run.id` outside a greenlet and the run dies with MissingGreenlet (open issue, run_service.py).
    Refreshing the same identity-mapped row keeps repair loops measurable without touching product code."""
    from app.models.agent import AiRun
    from app.services.agent.wiring import Toolbox

    class EvalToolbox(Toolbox):
        async def execute(self, ctx: Any, name: str, input: dict) -> Any:  # type: ignore[type-arg]
            result = await super().execute(ctx, name, input)
            await ctx.session.get(AiRun, ctx.run_id, populate_existing=True)
            return result

    return EvalToolbox()


def load_tasks(directory: Path = TASKS_DIR) -> list[dict[str, Any]]:
    tasks = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]
    ids = [t["id"] for t in tasks]
    if len(set(ids)) != len(ids):
        raise EvalError("duplicate task ids")
    return tasks


class ScriptedProvider(ModelProvider):
    """Plays the transcript one model turn at a time; past the end it repeats the last turn."""

    name = "script"

    def __init__(self, transcript: list[dict[str, Any]], usage: tuple[int, int] = (100, 50)) -> None:
        self.turns, self.usage, self.requests = transcript, usage, []  # type: ignore[var-annotated]

    async def complete(self, model: str, request: CompletionRequest) -> Completion:
        self.requests.append(request)
        i = min(len(self.requests), len(self.turns)) - 1
        turn = self.turns[i]
        return Completion(
            model="eval-script",
            text="",
            tool_calls=[ToolCall(id=f"c-{i}-{len(self.requests)}", name=turn["tool"], input=turn.get("input", {}))],
            usage=Usage(input_tokens=self.usage[0], output_tokens=self.usage[1]),
            stop_reason="tool_use",
        )

    def stream(self, model: str, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError


# -- spec path assertions -------------------------------------------------------------------------

_TOKEN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[([A-Za-z_]+)=([^\]]*)\])?$")
_MISSING = object()


def resolve(doc: Any, path: str) -> Any:
    """`entities[name=Sale].fields[name=amount].min_value` -> the value, or the _MISSING marker."""
    cur = doc
    for part in path.split("."):
        m = _TOKEN.match(part)
        if m is None:
            raise EvalError(f"bad path segment '{part}'")
        key, attr, val = m.groups()
        if not isinstance(cur, dict) or key not in cur:
            return _MISSING
        cur = cur[key]
        if attr is not None:
            if not isinstance(cur, list):
                return _MISSING
            hit = [x for x in cur if isinstance(x, dict) and str(x.get(attr)) == val]
            if not hit:
                return _MISSING
            cur = hit[0]
    return cur


def check_spec(spec: dict[str, Any], checks: list[dict[str, Any]]) -> list[str]:
    bad = []
    for c in checks:
        got = resolve(spec, c["path"])
        if "equals" in c:
            if got is _MISSING or got != c["equals"]:
                bad.append(f"spec {c['path']}: expected {c['equals']!r}, got {'missing' if got is _MISSING else repr(got)}")
        elif c.get("absent"):
            if got is not _MISSING:
                bad.append(f"spec {c['path']}: expected absent")
        elif got is _MISSING:
            bad.append(f"spec {c['path']}: missing")
    return bad


# -- the run --------------------------------------------------------------------------------------


async def run_task(
    task: dict[str, Any], client: Any, session_factory: async_sessionmaker[AsyncSession]
) -> TaskResult:
    """Drive one task. `client` is an authenticated httpx.AsyncClient on the app; the caller has
    pointed the workspace settings at a scratch directory."""
    from app.api.agent_runs import agent_deps
    from app.main import app
    from app.services.agent.run_service import AgentDeps
    from app.services.agent.wiring import Approvals, Gates

    t = task["transcript"]
    provider = ScriptedProvider(t, tuple(task.get("usage", (100, 50))))
    deps = AgentDeps(toolbox=eval_toolbox(), approvals=Approvals(), gates=Gates(), provider_factory=lambda key: provider)
    app.dependency_overrides[agent_deps] = lambda: deps
    pid = wid = None
    res = TaskResult(task_id=task["id"], passed=False)
    try:
        pid = (await _ok(client.post("/projects", json={"name": f"eval-{task['id']}"[:60]}), 201))["id"]
        await _apply_start(client, pid, task.get("starting_spec") or {})
        wid = (await _ok(client.post(f"/projects/{pid}/workspaces", json={"name": "draft"}), 201))["id"]
        rid = (await _ok(client.post(f"/projects/{pid}/agent/runs", json={"goal": task["goal"], "workspace_id": wid}), 201))["id"]
        run: dict[str, Any] = {}
        for _ in range(MAX_ROUNDS):
            run = await _ok(client.post(f"/projects/{pid}/agent/runs/{rid}/resume"), 200)
            if run["state"] == "awaiting_approval":
                await _decide_all(client, pid, res)
                continue
            break
        detail = await _ok(client.get(f"/projects/{pid}/agent/runs/{rid}?limit=500"), 200)
        run = {**run, **{k: detail[k] for k in ("state", "stop_code", "steps_used", "repairs_used")}}
        res.trace = [f"{x['tool_name']}:{x['ok']}:{str(x['output'])[:400]}" for x in detail["steps"] if x["kind"] == "tool"]
        res.state, res.stop_code = run["state"], run["stop_code"]
        res.stop_detail = str(detail.get("stop_detail") or "")[:300]
        res.steps_used, res.repairs_used = run["steps_used"], run["repairs_used"]
        finishes = [s for s in detail["steps"] if s["kind"] == "tool" and s["tool_name"] == "finish"]
        res.gate_failures = sum(1 for s in finishes if s["ok"] is False and (s["output"] or {}).get("failures"))
        res.gate_pass_first_try = res.gate_failures == 0 and res.state == "applied"
        res.plan_extensions = sum(
            1 for s in detail["steps"] if s["kind"] == "approval" and str((s["output"] or {}).get("subject", "")).startswith("extend plan")
        )
        async with session_factory() as s:
            rows = (await s.execute(select(AiCostLedger).where(AiCostLedger.run_id == uuid.UUID(rid)))).scalars().all()
            res.tokens = sum(r.input_tokens + r.output_tokens + r.cache_read_tokens + r.cache_write_tokens for r in rows)
            res.cost_micro_usd = sum(r.cost_micro_usd for r in rows)
        spec = await _ok(client.get(f"/projects/{pid}/spec"), 200)
        res.failures = _assert(task.get("expect", {}), res, spec)
        res.passed = not res.failures
    finally:
        app.dependency_overrides.pop(agent_deps, None)
        if pid and wid:
            await client.delete(f"/projects/{pid}/workspaces/{wid}")  # drops the checkpoint database
    return res


async def _ok(awaitable: Any, status: int) -> dict[str, Any]:
    r = await awaitable
    if r.status_code != status:
        raise EvalError(f"unexpected HTTP {r.status_code}: {r.text[:300]}")
    return dict(r.json())


async def _apply_start(client: Any, pid: str, start: dict[str, Any]) -> None:
    if not start:
        return
    spec = await _ok(client.get(f"/projects/{pid}/spec"), 200)
    spec.update(start)  # sections named by the task replace the empty ones
    await _ok(client.put(f"/projects/{pid}/spec", json=spec), 200)


async def _decide_all(client: Any, pid: str, res: TaskResult) -> None:
    pend = (await client.get(f"/projects/{pid}/agent/approvals?state=pending")).json()
    items = pend["items"] if isinstance(pend, dict) else pend
    for item in items:
        body: dict[str, Any] = {"approve": True}
        if item.get("payload_hash"):  # S3-005: bind the decision to what was read
            body["expected_payload_hash"] = item["payload_hash"]
        await _ok(client.post(f"/projects/{pid}/agent/approvals/{item['id']}/decision", json=body), 200)
        res.approvals += 1


def _assert(expect: dict[str, Any], res: TaskResult, spec: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    want = expect.get("state", "applied")
    if res.state != want:
        bad.append(f"final state {res.state} (stop {res.stop_code}: {res.stop_detail}), expected {want}")
    if expect.get("gates_green", True) and not res.gate_pass_first_try and want == "applied" and res.gate_failures:
        bad.append(f"gates refused the finish {res.gate_failures} time(s)")
    if res.plan_extensions > expect.get("max_plan_extensions", 0):
        bad.append(f"left the approved plan {res.plan_extensions} time(s)")
    if res.repairs_used > expect.get("max_repairs", 0):
        bad.append(f"repairs {res.repairs_used} > {expect.get('max_repairs', 0)}")
    return bad + check_spec(spec, expect.get("spec", []))


async def run_live(api_key: str | None = None) -> None:
    """Live mode (a real provider) is intentionally not wired: it never calls out from this suite."""
    if not api_key:
        raise EvalError("live mode needs a BYO provider key (organisation AI settings); none was given")
    raise EvalError("live mode is not wired yet: no real provider is called by the eval suite")
