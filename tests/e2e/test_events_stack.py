"""Transactional outbox and event bus end to end: generate the `events_orders` project (multi-tenant, two
entities, a state machine), migrate a real Postgres, run the project's own tests, then
tests/e2e/events_scenarios.py, which also starts real relay processes (and kills them with SIGKILL).
Needs Docker (testcontainers)."""

import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent

# The project owner's subscriber file (custom zone): every handler writes what it sees to a sink file,
# and can be slowed down or hung from the test through the environment.
SUBSCRIBERS = '''
import asyncio
import json
import os
import time

from app.events import bus
from app.events.bus import Event, subscribe


def _write(kind: str, event: Event) -> None:
    path = os.environ.get("EVENTS_SINK")
    if not path:
        return
    line = json.dumps({
        "kind": kind, "id": str(event.id), "type": event.type, "aggregate_id": str(event.aggregate_id),
        "seq": event.seq, "tenant": str(event.tenant_id), "ctx_tenant": str(bus.current_tenant_id()),
        "pid": os.getpid(), "t": time.time(), "payload": event.payload,
    })
    with open(path, "a", encoding="utf-8") as sink:
        sink.write(line + "\\n")


async def handle(event: Event) -> None:
    _write("start", event)
    if os.environ.get("EVENTS_SINK_HANG") == "1":
        await asyncio.sleep(3600)  # a relay killed here dies mid-delivery
    await asyncio.sleep(float(os.environ.get("EVENTS_SINK_DELAY", "0")))
    _write("done", event)


for _name in ("customer.created", "order.created", "order.updated", "order.deleted", "order.transitioned"):
    subscribe(_name)(handle)
'''


def test_the_events_project_behaves_as_specified(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "events_orders")
    shutil.copy(HERE / "events_scenarios.py", root / "tests" / "test_scenarios.py")
    (root / "app" / "hooks" / "subscribers.py").write_text(SUBSCRIBERS, encoding="utf-8")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/events_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "--ignore=tests/test_scenarios.py"], root, url))
    assert "passed" in output and "failed" not in output
    scenarios = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_scenarios.py"], root, url))
    assert "8 passed" in scenarios, scenarios
