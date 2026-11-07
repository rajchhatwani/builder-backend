"""B3-11: the agent eval suite. Fixed tasks run through the real driver, tools, approvals and gates with a
scripted model; the metrics are compared with the committed baseline (tests/agent_eval/baseline.json).
Set AGENT_EVAL_REPORT=<path> to also write the report, AGENT_EVAL_UPDATE_BASELINE=1 to refresh the baseline."""

import copy
import json
import os
import shutil
from pathlib import Path

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.services import workspace_service
from app.services.agent_eval import report as rep
from app.services.agent_eval.runner import BASELINE, EvalError, load_tasks, run_live, run_task

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
def ws_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str) -> Settings:
    s = Settings(environment="test", workspace_root=str(tmp_path / "ws"), workspace_db_admin_url=SecretStr(database_url))
    monkeypatch.setattr(workspace_service, "get_settings", lambda: s)
    return s


def test_there_are_at_least_five_fixed_tasks() -> None:
    tasks = load_tasks()
    assert len(tasks) >= 5
    for t in tasks:
        assert {"id", "goal", "starting_spec", "transcript", "expect"} <= set(t)


async def test_all_fixed_tasks_pass_deterministically_with_the_baseline(
    client: AsyncClient, session_factory: Factory, ws_settings: Settings
) -> None:
    results = [await run_task(t, client, session_factory) for t in load_tasks()]
    report = rep.build_report(results)
    out = os.environ.get("AGENT_EVAL_REPORT")
    if out:
        Path(out).write_text(rep.dumps(report), encoding="utf-8")
        Path(out).with_suffix(".md").write_text(rep.markdown(report), encoding="utf-8")
    if os.environ.get("AGENT_EVAL_UPDATE_BASELINE") == "1":
        BASELINE.write_text(rep.dumps(report), encoding="utf-8")
    failed = {r.task_id: (r.failures, r.trace) for r in results if not r.passed}
    assert not failed, failed
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert rep.compare(report, baseline) == []
    assert all(r.tokens > 0 and r.approvals >= 2 for r in results)


async def test_a_broken_transcript_is_reported_as_a_failure(
    client: AsyncClient, session_factory: Factory, ws_settings: Settings
) -> None:
    task = copy.deepcopy(next(t for t in load_tasks() if t["id"] == "validation_rule"))
    # the model edits an entity the approved plan does not cover: the run pauses to ask, nothing is applied
    task["transcript"][1] = {"tool": "add_entity", "input": {"entity": {"name": "Payroll"}}}
    res = await run_task(task, client, session_factory)
    assert not res.passed
    assert res.plan_extensions >= 1
    assert any("plan" in f for f in res.failures)


async def test_a_regression_against_the_baseline_is_flagged(
    client: AsyncClient, session_factory: Factory, ws_settings: Settings
) -> None:
    task = next(t for t in load_tasks() if t["id"] == "validation_rule")
    res = await run_task(task, client, session_factory)
    assert res.passed
    report = rep.build_report([res])
    base = rep.build_report([res])
    assert rep.compare(report, base) == []
    base["tasks"]["validation_rule"]["tokens"] = res.tokens // 2  # the baseline was much cheaper
    assert any("tokens up" in r for r in rep.compare(report, base))


async def test_live_mode_refuses_without_a_byo_key_and_never_calls_out() -> None:
    with pytest.raises(EvalError, match="BYO"):
        await run_live(None)
    with pytest.raises(EvalError, match="not wired"):
        await run_live("sk-test-not-used")
