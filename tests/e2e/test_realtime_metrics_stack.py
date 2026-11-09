"""Realtime + metrics end to end: generate the realtime_metrics project, migrate a real Postgres and run
tests/e2e/realtime_metrics_scenarios.py (two SSE clients, resume with Last-Event-ID, per-caller filtering, no field
values in events, metrics through the row scope). Then recompute every dumped metric with the builder's own
`compute()` over the same rows and require identical results. Needs Docker (testcontainers)."""
import json
import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from app.core.metrics import compute, parse_metric
from app.core.spec_models import Spec
from tests.e2e.test_generated_project import FIXTURES, ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent


def test_the_example_project_behaves_as_specified(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "realtime_metrics")
    shutil.copy(HERE / "realtime_metrics_scenarios.py", root / "tests" / "test_scenarios.py")
    dump = root / "metrics_dump.json"
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/realtime_metrics_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url, METRICS_DUMP=str(dump)))
    print(output)
    assert "passed" in output and "failed" not in output

    spec = Spec.model_validate_json((FIXTURES / "realtime_metrics.json").read_text(encoding="utf-8"))
    entities = {e.name: e for e in spec.entities}
    definitions = {d["key"]: parse_metric(d) for d in (spec.metrics_layer.definitions if spec.metrics_layer else [])}
    data = json.loads(dump.read_text(encoding="utf-8"))
    compared = 0
    for person, seen in data.items():
        tables = {"Expense": seen["expenses"], "Payroll": seen["payrolls"]}
        for key, got in seen["results"].items():
            definition = definitions[key]
            want = compute(definition, tables[definition.entity], entities[definition.entity]).as_dict()
            assert {k: got[k] for k in want} == want, (person, key, got, want)
            compared += 1
    assert compared >= 30  # 4 people x their readable metrics, every aggregate and the group-bys
