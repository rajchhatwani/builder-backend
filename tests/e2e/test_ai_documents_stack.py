"""The AI pack, documents block (D34) end to end: generate the ai_documents_knowledge project (multi-tenant, stage extract,
5 USD daily budget), migrate a real Postgres (upgrade, `alembic check`, downgrade, upgrade) and run
tests/e2e/ai_documents_scenarios.py inside it. FAKE provider only, no network. Needs Docker (testcontainers)."""
import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent


def test_document_ai_extracts_anchors_and_reviews(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "ai_documents_knowledge")
    shutil.copy(HERE / "ai_documents_scenarios.py", root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/ai_documents_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    print(output)
    assert "passed" in output and "failed" not in output
