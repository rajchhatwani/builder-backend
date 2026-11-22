"""API platform (D49/D50) end to end: generate the api_shop project, migrate a real Postgres (upgrade,
`alembic check`, downgrade, upgrade), run the project's own tests (including tests/test_platform_api.py) and then
tests/e2e/api_platform_scenarios.py inside it. Needs Docker (testcontainers)."""
import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent


def test_api_shop_keys_scopes_limits_and_apps(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "api_shop")
    shutil.copy(HERE / "api_platform_scenarios.py", root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/api_platform_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    print(output)
    assert "passed" in output and "failed" not in output
