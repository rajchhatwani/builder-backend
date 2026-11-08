"""State machines end to end: generate the example projects, migrate a real Postgres, run each project's
own tests plus the scenario file in tests/e2e/. Needs Docker (testcontainers)."""

import shutil
from pathlib import Path

import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent


@pytest.mark.parametrize(
    ("name", "scenarios"),
    [
        ("flow_invoices", "state_machine_invoice_scenarios.py"),
        ("flow_leave", "state_machine_leave_scenarios.py"),
        ("flow_abac", "state_machine_abac_scenarios.py"),
    ],
)
def test_the_example_flows_behave_as_specified(
    name: str,
    scenarios: str,
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, name)
    shutil.copy(HERE / scenarios, root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/{name}_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    assert "passed" in output and "failed" not in output
