"""Provider adapters and the per-tenant credential vault end to end: generate the `providers_notify`
project (multi-tenant, email + SMS adapters), migrate a real Postgres, run the project's own tests, then
tests/e2e/providers_scenarios.py (admin / non-admin / cross-tenant, rotation with the re-encrypt command
as a real process, emulator, breaker, production start-up refusal). Needs Docker (testcontainers).
Nothing here contacts a provider: the emulator is the only adapter."""

import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent


def test_the_providers_project_behaves_as_specified(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "providers_notify")
    shutil.copy(HERE / "providers_scenarios.py", root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/providers_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "--ignore=tests/test_scenarios.py"], root, url))
    assert "passed" in output and "failed" not in output
    scenarios = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_scenarios.py"], root, url))
    assert "7 passed" in scenarios, scenarios
