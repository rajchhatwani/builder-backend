"""The API edge end to end: generate the `api_edge_orders` project (multi-tenant, idempotency keys, rate
limits, quotas, dated API versions), migrate a real Postgres, run the project's own tests, then
tests/e2e/api_edge_scenarios.py, which starts real uvicorn processes (two at once) and drives them with
parallel HTTP requests (and kills one with SIGKILL in the middle of a write). Needs Docker (testcontainers)."""

import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent

# The project owner's version transformer (custom zone): the oldest shape called the id `legacy_id`.
API_VERSIONS = '''
from typing import Any


def undo_legacy_id(method: str, path: str, body: Any) -> Any:
    def one(item: Any) -> Any:
        if isinstance(item, dict) and "id" in item:
            item["legacy_id"] = item.pop("id")
        return item

    if isinstance(body, dict) and isinstance(body.get("items"), list):
        body["items"] = [one(i) for i in body["items"]]
        return body
    return one(body)


TRANSFORMERS = {"2026-11-01": undo_legacy_id}
'''

# A server for the scenarios: the same app, with limits and a slow write that the test chooses.
SERVER = '''
import asyncio
import os
import sys

import uvicorn

from app.api_edge import definitions

if os.environ.get("EDGE_USER_CAPACITY"):
    definitions.RATE_LIMITS["user"] = {  # type: ignore[index]
        "capacity": int(os.environ["EDGE_USER_CAPACITY"]),
        "refill_per_second": float(os.environ.get("EDGE_USER_REFILL", "0.05")),
    }
    definitions.RATE_LIMITS["groups"] = []  # type: ignore[index]

delay = float(os.environ.get("EDGE_WRITE_DELAY", "0"))
if delay:
    from app.crud.customers import CustomerRepository

    async def slow(_ctx: object) -> None:
        await asyncio.sleep(delay)

    CustomerRepository.hooks = {
        **CustomerRepository.hooks,
        "after_save": (*CustomerRepository.hooks.get("after_save", ()), slow),
    }

marker = os.environ.get("EDGE_MARKER_FILE")
if marker:
    import sqlalchemy as sa

    from app.crud.customers import CustomerRepository
    from app.db import session_factory

    async def mark(_ctx: object) -> None:
        # runs in after_commit: a second connection must already see the committed row
        async with session_factory() as session:
            seen = (await session.execute(sa.text("SELECT count(*) FROM customers"))).scalar_one()
        with open(marker, "a", encoding="utf-8") as out:
            out.write(f"{seen}\\n")

    CustomerRepository.hooks = {
        **CustomerRepository.hooks,
        "after_commit": (*CustomerRepository.hooks.get("after_commit", ()), mark),
    }

from app.main import app

uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
'''


def test_the_api_edge_project_behaves_as_specified(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "api_edge_orders")
    shutil.copy(HERE / "api_edge_scenarios.py", root / "tests" / "test_scenarios.py")
    (root / "app" / "hooks" / "api_versions.py").write_text(API_VERSIONS, encoding="utf-8")
    (root / "edge_server.py").write_text(SERVER, encoding="utf-8")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/edge_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    # The project's own tests; they replace the transformer file with their own stand-ins, which is why
    # the scenarios (below) are the ones that use the owner's file above.
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "--ignore=tests/test_scenarios.py"], root, url))
    assert "passed" in output and "failed" not in output
    scenarios = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_scenarios.py"], root, url))
    assert "7 passed" in scenarios, scenarios
