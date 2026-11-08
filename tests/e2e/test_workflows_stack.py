"""Durable workflows end to end: generate the `workflows_orders` project, migrate a real Postgres, run the
project's own tests, then tests/e2e/workflows_scenarios.py, which starts real worker processes (and kills them
with SIGKILL mid-step). Needs Docker (testcontainers)."""

import re
import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent

# The project owner's functions (custom zone): every one writes what it sees to a sink file; a step can hang on
# its first attempt (to be killed there) or fail through the run's input.
HANDLERS = '''
import asyncio
import json
import os
import time

from app.workflows.registry import StepContext, compensation, step


def _write(kind: str, ctx: StepContext) -> None:
    path = os.environ.get("WF_SINK")
    if not path:
        return
    line = json.dumps({
        "kind": kind, "run": str(ctx.run_id), "step": ctx.step, "attempt": ctx.attempt,
        "key": ctx.idempotency_key, "pid": os.getpid(), "t": time.time(),
    })
    with open(path, "a", encoding="utf-8") as sink:
        sink.write(line + "\\n")


async def _forward(ctx: StepContext) -> dict:
    _write("start", ctx)
    if os.environ.get("WF_HANG_STEP") == ctx.step and ctx.attempt == 1:
        await asyncio.sleep(3600)  # a worker killed here dies mid-step
    if ctx.input.get("fail_at") == ctx.step:
        raise RuntimeError("boom password=hunter2")
    await asyncio.sleep(float(ctx.input.get("sleep", 0)))
    _write("done", ctx)
    return {"step": ctx.step}


async def _undo(ctx: StepContext) -> None:
    _write("undo_start", ctx)
    if os.environ.get("WF_HANG_UNDO") == ctx.step and ctx.attempt == 1:
        await asyncio.sleep(3600)
    _write("undo", ctx)


@step("order_flow", "reserve_stock")
async def reserve_stock(ctx: StepContext) -> dict:
    return await _forward(ctx)


@step("order_flow", "charge_card")
async def charge_card(ctx: StepContext) -> dict:
    return await _forward(ctx)


@step("order_flow", "send_receipt")
async def send_receipt(ctx: StepContext) -> dict:
    return await _forward(ctx)


@step("receipt_flow", "prepare")
async def prepare(ctx: StepContext) -> dict:
    return await _forward(ctx)


@compensation("order_flow", "reserve_stock")
async def undo_reserve_stock(ctx: StepContext) -> None:
    await _undo(ctx)


@compensation("order_flow", "charge_card")
async def undo_charge_card(ctx: StepContext) -> None:
    await _undo(ctx)
'''


def test_the_workflows_project_behaves_as_specified(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "workflows_orders")
    shutil.copy(HERE / "workflows_scenarios.py", root / "tests" / "test_scenarios.py")
    (root / "app" / "hooks" / "workflows.py").write_text(HANDLERS, encoding="utf-8")
    # Make the scenarios fast: 2 second step timeouts (so a lease is 3 s) and a 1 second backoff base.
    definitions = root / "app" / "workflows" / "definitions.py"
    text = definitions.read_text(encoding="utf-8")
    patched, timeouts = re.subn(r"'timeout_seconds': (30|60)\b", "'timeout_seconds': 2", text)
    patched, backoffs = re.subn(r"'backoff_seconds': 5\b", "'backoff_seconds': 1", patched)
    assert timeouts == 5 and backoffs == 5, (timeouts, backoffs)
    definitions.write_text(patched, encoding="utf-8")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/wf_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "--ignore=tests/test_scenarios.py"], root, url))
    assert "passed" in output and "failed" not in output
    scenarios = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_scenarios.py"], root, url))
    assert "4 passed" in scenarios, scenarios
