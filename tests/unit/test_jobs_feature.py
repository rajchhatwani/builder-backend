"""Jobs (queue + scheduler + worker groups): the `jobs` block is validated, off by default (other projects are
untouched), and an enabled project gets the queue, handlers file, migration, compose services and tests."""

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_jobs import JOB_TABLES

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(change: Any = None, name: str = "jobs_invoices") -> Spec:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def test_the_example_is_valid() -> None:
    assert validate(spec_with()) == []


@pytest.mark.parametrize("backend", ["redis", "rabbitmq"])
def test_brokers_are_not_implemented_yet(backend: str) -> None:
    issues = [i for i in validate(spec_with(lambda d: d["jobs"]["queue"].update(backend=backend))) if i.path == "jobs.queue.backend"]
    assert [i.code for i in issues] == ["not_yet_implemented"]
    assert "postgres" in issues[0].message


def test_an_unknown_backend_is_refused() -> None:
    assert ("jobs.queue.backend", "unknown_backend") in codes(spec_with(lambda d: d["jobs"]["queue"].update(backend="sqs")))


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        ("jobs[0].timeout_seconds", 0, "invalid_value"),
        ("jobs[0].timeout_seconds", 21_601, "invalid_value"),
        ("jobs[0].retry.max_attempts", 0, "invalid_value"),
        ("jobs[0].retry.max_attempts", 51, "invalid_value"),
        ("jobs[0].retry.backoff_seconds", 0, "invalid_value"),
        ("jobs[0].retry.backoff", "random", "invalid_value"),
        ("jobs[0].name", "Send-Invoice", "invalid_name"),
        ("jobs[0].queue", "Q U", "invalid_name"),
        ("jobs[0].handler", "class", "invalid_handler"),
        ("jobs[0].handler", "a.b", "invalid_handler"),
        ("worker_groups[0].concurrency", 0, "invalid_value"),
        ("worker_groups[0].concurrency", 65, "invalid_value"),
        ("worker_groups[0].placement", "cloud", "invalid_value"),
        ("worker_groups[0].name", "Big Group", "invalid_name"),
        ("schedules[0].missed", "all", "invalid_value"),
        ("schedules[0].job", "nothing", "unknown_job"),
    ],
)
def test_values_are_checked(path: str, value: Any, code: str) -> None:
    def change(d: dict[str, Any]) -> None:
        section, _, rest = path.partition(".")
        index = int(section.split("[")[1].rstrip("]"))
        target = d["jobs"][section.split("[")[0]][index]
        keys = rest.split(".")
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value

    assert (f"jobs.{path}", code) in codes(spec_with(change))


@pytest.mark.parametrize(
    "cron",
    ["* * * * * *", "61 * * * *", "0 24 * * *", "0 0 * * 7", "@weekly", "0 0 31 2 *", "every monday", ""],
)
def test_cron_is_strict(cron: str) -> None:
    assert ("jobs.schedules[0].cron", "invalid_cron") in codes(spec_with(lambda d: d["jobs"]["schedules"][0].update(cron=cron)))


def test_an_unknown_timezone_is_refused() -> None:
    assert ("jobs.schedules[0].timezone", "invalid_timezone") in codes(
        spec_with(lambda d: d["jobs"]["schedules"][0].update(timezone="Mars/Base"))
    )


def test_a_queue_nobody_serves_is_refused() -> None:
    def change(d: dict[str, Any]) -> None:
        d["jobs"]["jobs"][0]["queue"] = "orphans"

    found = codes(spec_with(change))
    assert ("jobs.worker_groups", "queue_without_worker") in found  # "orphans" has no worker
    assert ("jobs.worker_groups[0].queues", "unknown_queue") in found  # and "default" now has no job


def test_a_group_may_not_name_a_queue_without_jobs() -> None:
    assert ("jobs.worker_groups[0].queues", "unknown_queue") in codes(
        spec_with(lambda d: d["jobs"]["worker_groups"][0].update(queues=["default", "ghost"]))
    )


def test_duplicates_are_refused() -> None:
    def change(d: dict[str, Any]) -> None:
        d["jobs"]["jobs"][1]["name"] = d["jobs"]["jobs"][0]["name"]
        d["jobs"]["jobs"][1]["handler"] = d["jobs"]["jobs"][0]["handler"]
        d["jobs"]["worker_groups"][1]["name"] = "default"
        d["jobs"]["schedules"].append(copy.deepcopy(d["jobs"]["schedules"][0]))

    found = codes(spec_with(change))
    assert ("jobs.jobs[1].name", "duplicate_name") in found
    assert ("jobs.jobs", "duplicate_handler") in found
    assert ("jobs.worker_groups[1].name", "duplicate_name") in found
    assert ("jobs.schedules[1].name", "duplicate_name") in found


def test_an_enabled_block_needs_jobs() -> None:
    def change(d: dict[str, Any]) -> None:
        d["jobs"].update(jobs=[], schedules=[], worker_groups=[])

    assert ("jobs.jobs", "no_jobs") in codes(spec_with(change))


def test_unknown_keys_and_wrong_types_are_refused_by_the_schema() -> None:
    with pytest.raises(ValueError):
        spec_with(lambda d: d["jobs"].update(broker="x"))
    with pytest.raises(ValueError):
        spec_with(lambda d: d["jobs"]["jobs"][0].update(timeout_seconds="soon"))


def test_job_tables_are_reserved() -> None:
    def clash(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = "jb_jobs"

    assert ("entities[0].table_name", "duplicate_name") in codes(spec_with(clash))
    assert JOB_TABLES == ("jb_jobs", "jb_schedule_fires", "jb_schedules")


def test_a_disabled_block_changes_nothing() -> None:
    plain = spec_with(lambda d: d.pop("jobs"))
    off = spec_with(lambda d: d["jobs"].update(enabled=False))
    assert generate(plain) == generate(off)
    text = "".join(generate(off).values())
    assert not any(p.startswith(("app/jobs/", "deploy/workers/")) or "jobs" in p for p in generate(off))
    assert "jb_jobs" not in text and "app.jobs" not in text and "worker-" not in text


@pytest.mark.parametrize("name", ["blog", "numbering", "demo_leave", "events_orders", "payments_stripe"])
def test_projects_without_the_block_have_no_job_files_or_wiring(name: str) -> None:
    files = generate(Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    assert not [p for p in files if p.startswith(("app/jobs", "deploy/workers")) or "0013" in p]
    assert not any("app.jobs" in text for p, text in files.items() if not p.startswith("app/payments/"))


def test_an_enabled_project_gets_the_queue_the_handlers_and_the_wiring() -> None:
    files = generate(spec_with())
    for path in (
        "app/jobs/models.py", "app/jobs/queue.py", "app/jobs/registry.py", "app/jobs/scheduler.py",
        "app/jobs/worker.py", "app/jobs/admin.py", "app/jobs/cron.py", "app/jobs/definitions.py",
        "app/hooks/jobs.py", "alembic/versions/0013_jobs.py", "tests/test_jobs.py",
    ):
        assert path in files, path
    assert "_job_models" in files["app/models/__init__.py"]
    for table in JOB_TABLES:
        assert table in files["tests/conftest.py"]
    zones = json.loads(files["platform/zones.json"])["zones"]
    assert zones["app/hooks/jobs.py"] == "custom" and zones["app/jobs/queue.py"] == "generated"
    assert zones["deploy/workers/reports/compose.yml"] == "seeded"
    stub = files["app/hooks/jobs.py"]
    assert "async def send_invoice(" in stub and "async def run_weekly_dunning(" in stub
    assert "@handler('weekly_dunning')" in stub


def test_the_claim_uses_skip_locked_and_a_lease_checked_finish() -> None:
    queue = generate(spec_with())["app/jobs/queue.py"]
    assert "with_for_update(skip_locked=True)" in queue
    assert queue.count("Job.lease_token == job.lease_token") == 2  # complete and fail both need the lease
    assert "type(exc).__name__" in queue  # only the class is stored
    assert "payload" not in re.findall(r"logger\.\w+\(([^)]*)\)", queue).__str__()


def test_the_cron_module_in_the_project_is_the_builders() -> None:
    from app.core import jobs_cron

    assert generate(spec_with())["app/jobs/cron.py"] == Path(jobs_cron.__file__).read_text(encoding="utf-8")


def test_same_server_groups_become_compose_services_and_separate_ones_a_bundle() -> None:
    files = generate(spec_with())
    compose = yaml.safe_load(files["docker-compose.yml"])
    assert "worker-default" in compose["services"] and "worker-reports" not in compose["services"]
    svc = compose["services"]["worker-default"]
    assert svc["command"] == ["python", "-m", "app.jobs.worker", "--group", "default"]
    assert svc["environment"]["DB_POOL_SIZE"].endswith("6}")  # concurrency 4 + 2
    assert svc["depends_on"]["api"]["condition"] == "service_healthy"
    bundle = yaml.safe_load(files["deploy/workers/reports/compose.yml"])
    worker = bundle["services"]["worker-reports"]
    assert worker["command"][-2:] == ["--group", "reports"]
    assert "${DATABASE_URL:?" in worker["environment"]["DATABASE_URL"]
    assert "DATABASE_URL=" in files["deploy/workers/reports/.env.example"]
    assert "app/jobs/worker.py" in files and "deploy/workers/default/compose.yml" not in files


def test_the_migration_chains_after_the_other_blocks() -> None:
    files = generate(spec_with())
    migration = files["alembic/versions/0013_jobs.py"]
    assert 'op.create_index("ix_jb_jobs_claim", "jb_jobs", ["queue", "status", "run_at"])' in migration
    assert "uq_jb_jobs_dedupe_key" in migration and "pk_jb_schedule_fires" in migration
    revisions = {
        m.group(1): m.group(2)
        for path, text in files.items()
        if path.startswith("alembic/versions/")
        for m in [re.search(r'^revision: str = "(\w+)"\ndown_revision: str \| None = (?:"(\w+)"|None)$', text, re.M)]
        if m
    }
    heads = set(revisions) - {v for v in revisions.values() if v}
    assert heads == {"0013"}


def test_jobs_chain_after_events_when_both_are_on() -> None:
    def both(d: dict[str, Any]) -> None:
        d["events"] = {"enabled": True}

    files = generate(spec_with(both))
    assert 'down_revision: str | None = "0009"' in files["alembic/versions/0013_jobs.py"]


def test_the_definitions_are_plain_data() -> None:
    namespace: dict[str, Any] = {}
    exec(compile(generate(spec_with())["app/jobs/definitions.py"], "definitions", "exec"), namespace)  # noqa: S102
    assert namespace["JOBS"]["send_invoice"]["retry"] == {"max_attempts": 4, "backoff_seconds": 5, "backoff": "exponential"}
    assert namespace["SCHEDULES"]["weekly_dunning_monday"]["timezone"] == "Asia/Kolkata"
    assert namespace["GROUPS"]["reports"]["placement"] == "separate_server"


def test_the_dedupe_key_is_unique_per_tenant_and_fire_records_are_purged() -> None:
    from app.core.generator import generate

    files = generate(spec_with())
    assert "uq_jb_jobs_tenant_dedupe_key" in files["alembic/versions/0013_jobs.py"]
    assert "fire_retention_days" in files["app/jobs/queue.py"] and "tenant_id" in files["app/jobs/queue.py"]
