"""ABAC and PBAC end to end: generate the project, migrate a real Postgres, run the project's own
tests plus the scenario tests in tests/e2e/authz_scenarios/ (who may do what, row by row).
Needs Docker (testcontainers), not `docker compose`."""

import shutil
from pathlib import Path

import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

SCENARIOS = Path(__file__).resolve().parent / "authz_scenarios"


@pytest.mark.parametrize("name", ["authz_abac", "authz_pbac", "authz_tenant"])
def test_policies_are_enforced_by_the_generated_project(
    name: str,
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    root = project_dir(tmp_path_factory, name)
    scenarios = SCENARIOS / f"{name.removeprefix('authz_')}_scenarios.py"
    shutil.copy(scenarios, root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/{name}_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "-x"], root, url))
    assert "passed" in output and "failed" not in output
    # the generic smoke test is replaced by policy tests, and says why
    assert "skipped" in output
