"""Custom fields end to end: generate the example project, migrate a real Postgres, promote a custom field
with the generated data-moving migration, downgrade it, and run the scenario file in tests/e2e/.
Needs Docker (testcontainers)."""

import json
import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from app.core.custom_fields import promote
from app.core.spec_models import Spec
from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent
SPEC = HERE.parent / "fixtures" / "specs" / "custom_fields.json"


def test_the_example_project_behaves_as_specified(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "custom_fields")
    spec = Spec.model_validate(json.loads(SPEC.read_text(encoding="utf-8")))
    for field in ("score", "tier"):
        _, plan = promote(spec, "Contact", field)
        (root / "tests" / f"promote_{field}.txt").write_text(
            plan.render_migration(f"0002_{field}", "0001"), encoding="utf-8"
        )
    shutil.copy(HERE / "custom_fields_scenarios.py", root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/cf_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    assert "passed" in output and "failed" not in output
