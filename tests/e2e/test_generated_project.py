"""M5 proof, part 1: boot a real Postgres, apply the generated migration, and run the
generated project's own smoke tests against it. Needs Docker (testcontainers) but not
`docker compose`; see test_compose_stack.py for the full stack.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.community.postgres import PostgresContainer

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


@pytest.fixture(scope="module")
def postgres() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


def project_dir(tmp_path_factory: pytest.TempPathFactory, name: str) -> Path:
    spec = Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    root = tmp_path_factory.mktemp(name)
    for path, content in generate(spec).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root


def run(args: list[str], cwd: Path, database_url: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=600
    )


def ok(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, f"{result.args}\n{result.stdout}\n{result.stderr}"
    return result.stdout


@pytest.mark.parametrize("name", ["blog", "library"])
def test_generated_project_migrates_and_passes_its_own_tests(
    name: str, postgres: PostgresContainer, tmp_path_factory: pytest.TempPathFactory
) -> None:
    root = project_dir(tmp_path_factory, name)
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/{name}_test"
    )

    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    # The models and the rendered migration must describe the same schema.
    ok(run(["-m", "alembic", "check"], root, url))
    # The migration must be reversible.
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))

    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    assert "passed" in output
    assert "failed" not in output
