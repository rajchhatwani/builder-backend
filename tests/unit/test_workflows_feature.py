"""Durable workflows: the `workflows` block is validated (fail closed), off by default, and an enabled project
gets the runner, the API, the worker service, the migration and its tests."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_workflows import WORKFLOW_TABLES

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(change: Any = None, name: str = "workflows_orders") -> Spec:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def wf(d: dict[str, Any], i: int = 0) -> dict[str, Any]:
    return d["workflows"]["workflows"][i]


def test_the_example_is_valid() -> None:
    assert validate(spec_with()) == []


def test_the_block_is_off_by_default_and_other_projects_get_no_workflow_files() -> None:
    for spec in (spec_with(lambda d: d.update(workflows=None)), spec_with(lambda d: d["workflows"].update(enabled=False))):
        files = generate(spec)
        assert not [p for p in files if "workflows" in p]
        assert not any("app.workflows" in t or "workflow-worker" in t for t in files.values())
    assert not [p for p in generate(spec_with(name="jobs_invoices")) if "workflows" in p]


CASES: list[tuple[str, Any, tuple[str, str]]] = [
    ("dbos_not_yet", lambda d: d["workflows"].update(runtime="dbos"), ("workflows.runtime", "not_yet_implemented")),
    ("temporal_not_yet", lambda d: d["workflows"].update(runtime="temporal"), ("workflows.runtime", "not_yet_implemented")),
    ("unknown_runtime", lambda d: d["workflows"].update(runtime="cron"), ("workflows.runtime", "unknown_runtime")),
    ("needs_auth", lambda d: d.update(auth=None), ("workflows", "needs_auth")),
    ("no_workflows", lambda d: d["workflows"].update(workflows=[]), ("workflows.workflows", "no_workflows")),
    ("bad_name", lambda d: wf(d).update(name="Order Flow"), ("workflows.workflows[0].name", "invalid_name")),
    ("duplicate_workflow", lambda d: wf(d, 1).update(name="order_flow"), ("workflows.workflows[1].name", "duplicate_name")),
    ("no_roles_default_deny", lambda d: wf(d).update(roles=[]), ("workflows.workflows[0].roles", "no_roles")),
    ("unknown_role", lambda d: wf(d).update(roles=["ghost"]), ("workflows.workflows[0].roles", "unknown_role")),
    ("no_steps", lambda d: wf(d).update(steps=[]), ("workflows.workflows[0].steps", "no_steps")),
    ("bad_policy", lambda d: wf(d).update(on_failure="ignore"), ("workflows.workflows[0].on_failure", "invalid_value")),
    ("bad_workflow_timeout", lambda d: wf(d).update(timeout_seconds=0), ("workflows.workflows[0].timeout_seconds", "invalid_value")),
    ("duplicate_step", lambda d: wf(d)["steps"][1].update(name="reserve_stock"), ("workflows.workflows[0].steps[1].name", "duplicate_name")),
    ("bad_step_name", lambda d: wf(d)["steps"][0].update(name="9bad"), ("workflows.workflows[0].steps[0].name", "invalid_name")),
    ("bad_kind", lambda d: wf(d)["steps"][0].update(kind="action"), ("workflows.workflows[0].steps[0].kind", "invalid_value")),
    ("job_kind_without_job", lambda d: wf(d)["steps"][0].update(kind="job"), ("workflows.workflows[0].steps[0].job", "missing_job")),
    ("job_on_hook_step", lambda d: wf(d)["steps"][0].update(job="send_receipt_email"), ("workflows.workflows[0].steps[0].job", "unexpected_job")),
    ("unknown_job", lambda d: wf(d, 1)["steps"][1].update(job="ghost"), ("workflows.workflows[1].steps[1].job", "unknown_job")),
    ("job_without_jobs_block", lambda d: d.update(jobs=None), ("workflows.workflows[1].steps[1].job", "needs_jobs")),
    ("bad_step_timeout", lambda d: wf(d)["steps"][0].update(timeout_seconds=10**7), ("workflows.workflows[0].steps[0].timeout_seconds", "invalid_value")),
    ("bad_attempts", lambda d: wf(d)["steps"][0]["retry"].update(max_attempts=0), ("workflows.workflows[0].steps[0].retry.max_attempts", "invalid_value")),
    ("bad_backoff", lambda d: wf(d)["steps"][0]["retry"].update(backoff="random"), ("workflows.workflows[0].steps[0].retry.backoff", "invalid_value")),
    ("bad_concurrency", lambda d: d["workflows"]["worker"].update(concurrency=0), ("workflows.worker.concurrency", "invalid_value")),
    (
        "compensate_policy_with_nothing_to_undo",
        lambda d: [s.update(compensate=False) for s in wf(d)["steps"]],
        ("workflows.workflows[0].on_failure", "nothing_to_compensate"),
    ),
]


@pytest.mark.parametrize(("name", "change", "expected"), CASES, ids=[c[0] for c in CASES])
def test_bad_configuration_is_refused(name: str, change: Any, expected: tuple[str, str]) -> None:
    assert expected in codes(spec_with(change)), (name, codes(spec_with(change)))


def test_a_table_name_clash_is_refused() -> None:
    def clash(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = WORKFLOW_TABLES[0]

    assert any(c == "duplicate_name" for _, c in codes(spec_with(clash)))


def test_an_enabled_project_gets_the_runner_api_worker_migration_and_tests() -> None:
    files = generate(spec_with())
    for path in (
        "app/workflows/engine.py", "app/workflows/worker.py", "app/workflows/router.py", "app/workflows/models.py",
        "app/workflows/registry.py", "app/workflows/definitions.py", "app/hooks/workflows.py",
        "alembic/versions/0020_workflows.py", "tests/test_workflows.py",
    ):
        assert path in files, path
    assert "workflow-worker:" in files["docker-compose.yml"]
    assert "app.workflows.router" in files["app/main.py"] and "_workflows_router" in files["app/main.py"]
    assert "_workflow_models" in files["app/models/__init__.py"]
    assert "wf_runs" in files["tests/conftest.py"]
    assert 'down_revision: str | None = "0013"' in files["alembic/versions/0020_workflows.py"]  # chained after jobs


def test_the_definitions_carry_the_spec() -> None:
    text = generate(spec_with())["app/workflows/definitions.py"]
    ns: dict[str, Any] = {}
    exec(text, ns)  # noqa: S102 (plain data generated from the spec)
    assert ns["RUNTIME"] == "postgres" and ns["MULTI_TENANT"] is True
    assert [s["name"] for s in ns["WORKFLOWS"]["order_flow"]["steps"]] == ["reserve_stock", "charge_card", "send_receipt"]
    assert ns["WORKFLOWS"]["order_flow"]["roles"] == ["admin", "manager"]


def test_generation_is_deterministic() -> None:
    assert generate(spec_with()) == generate(spec_with())


def test_no_input_or_result_value_can_reach_the_api_schema() -> None:
    router = generate(spec_with())["app/workflows/router.py"]
    out = router.split("class RunOut", 1)[1].split("def _allowed", 1)[0]
    assert "input" not in out.replace("RunDetail", "") and "result" not in out
