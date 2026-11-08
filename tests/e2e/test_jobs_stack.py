"""Background jobs end to end: generate the `jobs_invoices` project, migrate a real Postgres, run the project's own
tests, then tests/e2e/jobs_scenarios.py, which starts real worker processes (and kills one with SIGKILL).
Needs Docker (testcontainers)."""

import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent

# The project owner's handler file (custom zone): every handler writes what it sees to a sink file, and the
# test can hang the first attempt of a job (to kill the worker there) or make a job fail through its payload.
HANDLERS = '''
import asyncio
import json
import os
import time

from app.jobs.registry import JobContext, handler


def _write(kind: str, ctx: JobContext) -> None:
    path = os.environ.get("JOBS_SINK")
    if not path:
        return
    line = json.dumps({
        "kind": kind, "job_id": str(ctx.job_id), "name": ctx.name, "attempt": ctx.attempt,
        "pid": os.getpid(), "t": time.time(), "payload": ctx.payload,
    })
    with open(path, "a", encoding="utf-8") as sink:
        sink.write(line + "\\n")


@handler("send_invoice")
async def send_invoice(ctx: JobContext) -> None:
    _write("start", ctx)
    if os.environ.get("JOBS_HANG_FIRST") == "1" and ctx.attempt == 1:
        await asyncio.sleep(3600)  # a worker killed here dies mid-job
    if ctx.payload.get("fail"):
        raise RuntimeError("boom password=hunter2")
    await asyncio.sleep(float(ctx.payload.get("sleep", 0)))
    _write("done", ctx)


@handler("weekly_dunning")
async def run_weekly_dunning(ctx: JobContext) -> None:
    _write("start", ctx)
    _write("done", ctx)
'''


def test_the_jobs_project_behaves_as_specified(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "jobs_invoices")
    shutil.copy(HERE / "jobs_scenarios.py", root / "tests" / "test_scenarios.py")
    (root / "app" / "hooks" / "jobs.py").write_text(HANDLERS, encoding="utf-8")
    # Make the scenarios fast: a 2 second timeout (so a lease is 3 s) and a 1 second backoff base.
    definitions = root / "app" / "jobs" / "definitions.py"
    text = definitions.read_text(encoding="utf-8")
    assert "'timeout_seconds': 60" in text and "'backoff_seconds': 5" in text
    definitions.write_text(
        text.replace("'timeout_seconds': 60", "'timeout_seconds': 2").replace("'backoff_seconds': 5", "'backoff_seconds': 1"),
        encoding="utf-8",
    )
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/jobs_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "--ignore=tests/test_scenarios.py"], root, url))
    assert "passed" in output and "failed" not in output
    scenarios = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_scenarios.py"], root, url))
    assert "5 passed" in scenarios, scenarios
