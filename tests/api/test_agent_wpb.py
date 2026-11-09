"""WP-B (Cycle 4) api tests: pause and gate-run endpoints (G3, FX-7), the empty-finish stop (FX-9),
and the persisted promotion with its sweeper retry (FX-3 / B-004). The model is a script, never a provider."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.config import Settings, get_settings
from app.exceptions import AppError
from app.models.agent import AiRun, AiStep
from app.services.agent import wiring
from app.services.agent.contract import RuleFailure, ToolResult
from app.services.agent.sweeper import retry_promotions, sweep_once
from tests.api._approval_hash import reviewer_sends_hash  # noqa: F401  (isort: skip)
from tests.api import test_agent_e2e as e2e
from tests.api import test_agent_fb2b as fb2b
from tests.api import test_agent_runs as light
from tests.api._auth_helpers import make_project
from tests.api.test_agent_e2e import (  # noqa: F401  (fixtures)
    Script,
    _capture_factory,
    _cleanup,
    _decide,
    _resume,
    _setup,
    call,
    install as e2e_install,
    ws_settings,
)
from tests.api.test_agent_runs import (  # noqa: F401  (fixtures)
    FakeToolbox,
    ScriptedProvider,
    finish,
    install,
)


def _u(pid: str, rid: str, tail: str = "") -> str:
    return f"/projects/{pid}/agent/runs/{rid}{tail}"


# -- G3: pause ------------------------------------------------------------------------------------


async def test_pause_stops_the_driver_at_the_next_step_and_resume_lifts_it(client: AsyncClient, install: Any, session_factory: Any) -> None:
    pid = await make_project(client)
    rid = await light._new(client, pid)
    holder: dict[str, Any] = {}

    def handler(name: str, inp: dict[str, Any]) -> ToolResult:
        holder["paused_during_tool"] = True
        return ToolResult(ok=True, data={"v": 1})

    provider = ScriptedProvider(lambda n, r: light.call("read_thing", f"t{n}") if n < 6 else finish(n))
    tb = FakeToolbox(handler)
    install(provider, tb)
    # a person pauses while the run is live (state `planning` after the first drive step)
    await light._patch_run(session_factory, rid, state="planning")
    paused = await client.post(_u(pid, rid, "/pause"))
    assert paused.status_code == 200 and paused.json()["paused_at"] is not None
    again = await client.post(_u(pid, rid, "/pause"))
    assert again.status_code == 409 and again.json()["code"] == "illegal_transition"  # already paused
    # a paused run is not re-driven by the sweeper
    from app.services.agent.run_service import AgentDeps

    await light._patch_run(session_factory, rid, lease_until=datetime.now(UTC) - timedelta(minutes=5))
    taken = await sweep_once(session_factory, AgentDeps(toolbox=tb, approvals=light.FakeApprovals(session_factory),
                                                        provider_factory=lambda k: provider, gates=light.FakeGates()), get_settings())
    assert uuid.UUID(rid) not in taken and provider.requests == []
    # resume lifts the pause and drives
    r = await client.post(_u(pid, rid, "/resume"))
    assert r.status_code == 200 and r.json()["paused_at"] is None
    assert provider.requests  # the model was asked again


async def test_a_pause_set_while_the_run_is_driving_ends_the_drive_at_the_next_step(client: AsyncClient, install: Any, session_factory: Any) -> None:
    pid = await make_project(client)
    rid = await light._new(client, pid)
    calls = {"n": 0}

    async def pausing(n: int, request: Any) -> None:  # noqa: ARG001
        return None

    def handler(name: str, inp: dict[str, Any]) -> ToolResult:
        calls["n"] += 1
        return ToolResult(ok=True, data={"v": calls["n"]})

    class PausingToolbox(FakeToolbox):
        async def execute(self, ctx: Any, name: str, input: dict[str, Any]) -> ToolResult:  # noqa: A002
            out = await super().execute(ctx, name, input)
            async with session_factory() as s:  # the person clicks Pause while this tool runs
                await s.execute(update(AiRun).where(AiRun.id == ctx.run_id).values(paused_at=datetime.now(UTC)))
                await s.commit()
            return out

    provider = ScriptedProvider(lambda n, r: light.call("read_thing", f"p{n}") if n < 10 else finish(n))
    install(provider, PausingToolbox(handler))
    r = await client.post(_u(pid, rid, "/resume"))
    body = r.json()
    assert r.status_code == 200 and body["state"] in ("planning", "running") and body["paused_at"] is not None
    assert len(provider.requests) == 1 and calls["n"] == 1  # one model turn, one tool, then it stopped
    steps = await light._steps(session_factory, rid)
    assert any((s.output or {}).get("paused") is True for s in steps)
    assert body["stop_code"] is None  # paused is not stopped: the draft and the slot are kept


async def test_pause_refuses_a_finished_run_and_other_projects_and_viewers(client: AsyncClient, install: Any) -> None:
    install(ScriptedProvider(lambda n, r: finish(n)))
    p1, p2 = await make_project(client, "One"), await make_project(client, "Two")
    rid = await light._new(client, p1)
    assert (await client.post(_u(p2, rid, "/pause"))).status_code == 404
    assert (await client.post(_u(p1, rid, "/cancel"))).status_code == 200
    r = await client.post(_u(p1, rid, "/pause"))
    assert r.status_code == 409 and r.json()["code"] == "illegal_transition"


# -- FX-7: human gate run -----------------------------------------------------------------------------


async def test_gate_run_endpoint_returns_the_report_of_the_draft(client: AsyncClient, install: Any) -> None:
    class Gates(light.FakeGates):
        async def check_report(self, run: Any) -> tuple[list[RuleFailure], str]:
            return [RuleFailure("g8.secret", "app/x.py:1", "no secret", "a secret", "use the vault")], "h" * 64

    install(ScriptedProvider(lambda n, r: finish(n)), gates=Gates())
    pid = await make_project(client)
    rid = await light._new(client, pid)
    r = await client.post(_u(pid, rid, "/gates"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False and body["failure_count"] == 1 and body["report_hash"] == "h" * 64
    assert body["failures"][0]["rule_id"] == "g8.secret"
    await client.post(_u(pid, rid, "/cancel"))
    assert (await client.post(_u(pid, rid, "/gates"))).status_code == 409  # a finished run has no draft to gate


# -- FX-9: an empty finish is not a success ------------------------------------------------------------


async def test_finishing_a_build_with_no_change_stops_as_no_changes(client: AsyncClient, ws_settings: Settings) -> None:
    pid, _ws, rid = await _setup(client)
    e2e_install(Script([
        call("finish", summary="plan", plan={"entities": ["Invoice"], "hooks": [], "zones": [], "dependencies": []}),
        call("finish", summary="nothing to do"),
    ]))  # fmt: skip
    await _resume(client, pid, rid)
    await _decide(client, pid)
    run = await _resume(client, pid, rid, allow_stop=True)
    assert run["state"] == "stopped" and run["stop_code"] == "no_changes", run
    assert "nothing was applied" in run["stop_detail"]
    steps = (await client.get(_u(pid, rid))).json()["steps"]
    assert any(f.get("rule_id") == "agent.no_changes" for s in steps for f in (s["output"] or {}).get("failures", []))
    assert "Invoice" not in str((await client.get(f"/projects/{pid}/entities")).json())  # live spec untouched
    async with e2e._FACTORY() as s:
        assert (await s.get(AiRun, uuid.UUID(rid))).state != "applied"  # type: ignore[union-attr]


async def test_a_change_is_still_finished_normally(client: AsyncClient, ws_settings: Settings) -> None:
    pid, rid = await e2e._to_final_review(client)  # one add_entity then finish -> final review, not a no-changes stop
    pend = await e2e._pending(client, pid)
    assert pend["payload"]["final"] is True and pend["payload"]["empty_change"] is False


# -- FX-3 / B-004: the promotion list is stored with the apply and retried ------------------------------


async def _promotion(rid: str) -> dict[str, Any] | None:
    async with e2e._FACTORY() as s:
        run = await s.get(AiRun, uuid.UUID(rid))
        return None if run is None else run.promotion


async def test_a_crashed_promotion_is_stored_and_the_sweeper_commits_it(
    client: AsyncClient, ws_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, rid, final = await fb2b._hook_run_to_final(client)
    real = wiring.Approvals.promote
    state = {"fail": True}

    async def flaky(self: Any, run: Any, files: dict[str, bytes]) -> dict[str, Any]:
        if state["fail"]:
            raise AppError("git_failed", "the process died before the commit", 500)
        return await real(self, run, files)

    monkeypatch.setattr(wiring.Approvals, "promote", flaky)
    await _decide(client, pid)
    run = await _resume(client, pid, rid, allow_stop=True)
    assert run["state"] == "applied"  # the spec is live ...
    assert fb2b._main_file(ws_settings, pid, "app/custom/hooks/h1.py") is None  # ... the code is not yet
    doc = await _promotion(rid)
    assert doc is not None and doc["state"] == "pending" and set(doc["files"]) >= {"app/custom/hooks/h1.py"}
    assert any("promotion_failed" in str(s["output"]) for s in await e2e._steps(client, pid, rid))
    # too young: the sweeper leaves a promotion the first attempt may still be doing
    state["fail"] = False
    deps = wiring.default_deps()
    assert await retry_promotions(e2e._FACTORY, deps, get_settings()) == []
    done = await retry_promotions(e2e._FACTORY, deps, get_settings(), min_age_seconds=0)
    assert done == [uuid.UUID(rid)]
    assert fb2b.HOOK_BODY in (fb2b._main_file(ws_settings, pid, "app/custom/hooks/h1.py") or "")
    after = await _promotion(rid)
    assert after is not None and after["state"] == "done" and after["files"] == sorted(doc["files"])
    assert "app/custom/hooks/h1.py" in after["files"] and not any(isinstance(v, str) and len(v) > 200 for v in after["files"])
    assert await retry_promotions(e2e._FACTORY, deps, get_settings(), min_age_seconds=0) == []  # nothing left
    async with e2e._FACTORY() as s:
        steps = (await s.execute(select(AiStep).where(AiStep.run_id == uuid.UUID(rid)))).scalars().all()
    assert any((st.output or {}).get("retried") == 1 and "promotion" in (st.output or {}) for st in steps)


async def test_a_promotion_that_keeps_failing_is_given_up_loudly(
    client: AsyncClient, ws_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.agent import promote

    pid, rid, final = await fb2b._hook_run_to_final(client)

    async def always(self: Any, run: Any, files: dict[str, bytes]) -> dict[str, Any]:
        raise AppError("base_changed", "main moved", 409)

    monkeypatch.setattr(wiring.Approvals, "promote", always)
    await _decide(client, pid)
    await _resume(client, pid, rid, allow_stop=True)
    deps = wiring.default_deps()
    for _ in range(promote.MAX_PROMOTION_ATTEMPTS):
        await retry_promotions(e2e._FACTORY, deps, get_settings(), min_age_seconds=0)
    doc = await _promotion(rid)
    assert doc is not None and doc["state"] == "failed" and doc["attempts"] == promote.MAX_PROMOTION_ATTEMPTS
    assert await retry_promotions(e2e._FACTORY, deps, get_settings(), min_age_seconds=0) == []
    steps = await e2e._steps(client, pid, rid)
    assert any((s["output"] or {}).get("gave_up") is True for s in steps)


async def test_a_run_without_custom_files_stores_no_promotion(client: AsyncClient, ws_settings: Settings) -> None:
    pid, rid = await e2e._to_final_review(client)
    await _decide(client, pid)
    run = await _resume(client, pid, rid, allow_stop=True)
    assert run["state"] == "applied" and await _promotion(rid) is None


