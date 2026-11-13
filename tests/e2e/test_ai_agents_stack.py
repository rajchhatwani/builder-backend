"""The AI pack, agent runtime D37 (autonomy dial, approvals, eval gate) end to end: generate the ai_agents_evals project (multi-tenant, agents autopilot / drafter / guarded /
watcher, eval suites, 5 USD daily budget), migrate a real Postgres (upgrade, `alembic check`, downgrade, upgrade) and run
tests/e2e/ai_agents_scenarios.py inside it. FAKE provider only, no network. Needs Docker (testcontainers)."""
import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent


def test_agent_runtime_autonomy_dial_and_approvals(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "ai_agents_evals")
    shutil.copy(HERE / "ai_agents_scenarios.py", root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/ai_agents_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    print(output)
    assert "passed" in output and "failed" not in output
