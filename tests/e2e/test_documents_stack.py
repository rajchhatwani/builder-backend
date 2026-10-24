"""Documents bound to stored records, end to end: generate the project, migrate a real Postgres, run the
project's own tests plus tests/e2e/documents_scenarios.py. Needs Docker (testcontainers)."""

import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

SCENARIOS = Path(__file__).resolve().parent / "documents_scenarios.py"


def test_a_record_document_follows_the_entity_access_rules(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "docs_desk")
    shutil.copy(SCENARIOS, root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/docs_desk_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(
        run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_scenarios.py"], root, url)
    )
    assert "passed" in output and "failed" not in output
