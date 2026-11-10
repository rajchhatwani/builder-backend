"""CSV import / export in a generated project end to end: generate the search project, migrate a real
Postgres and run tests/e2e/data_import_scenarios.py (partial rejects, idempotent re-upload, field access,
formula neutralization, dry run). Needs Docker (testcontainers)."""
import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent


def test_the_example_project_imports_and_exports_as_specified(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "search")
    shutil.copy(HERE / "data_import_scenarios.py", root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/data_import_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    assert "passed" in output and "failed" not in output
