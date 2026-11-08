"""API edge (idempotency keys, rate limits and quotas, dated API versions): the `api_edge` block is
validated strictly, off by default (other projects are untouched), and an enabled project gets the
middleware, guard, tables, migration, custom transformer file and tests."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_api_edge import API_EDGE_TABLES, api_edge_tables

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(change: Any = None, name: str = "api_edge_orders") -> Spec:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def test_the_example_is_valid() -> None:
    assert validate(spec_with()) == []


def test_unknown_keys_and_wrong_types_are_refused_by_the_schema() -> None:
    for change in (
        lambda d: d["api_edge"].update(cache=True),
        lambda d: d["api_edge"]["idempotency"].update(scope="global"),
        lambda d: d["api_edge"]["rate_limits"].update(redis=True),
        lambda d: d["api_edge"]["rate_limits"]["user"].update(burst=1),
        lambda d: d["api_edge"]["rate_limits"]["groups"][0].update(weight=1),
        lambda d: d["api_edge"]["quotas"][0].update(reset="never"),
        lambda d: d["api_edge"]["versioning"].update(sunset="2030-01-01"),
        lambda d: d["api_edge"]["versioning"]["versions"][0].update(breaking=True),
        lambda d: d["api_edge"]["idempotency"].update(ttl_hours="a day"),
    ):
        with pytest.raises(ValueError):
            spec_with(change)


def test_an_enabled_block_must_turn_something_on() -> None:
    def empty(d: dict[str, Any]) -> None:
        d["api_edge"] = {"enabled": True}

    assert ("api_edge", "empty") in codes(spec_with(empty))


@pytest.mark.parametrize("hours", [0, -1, 169, 720, 721, 10**6])
def test_idempotency_ttl_must_be_in_range(hours: object) -> None:
    # 168 hours (7 days) is the cap: a replay is served before the route's authorization re-check
    assert ("api_edge.idempotency.ttl_hours", "invalid_value") in codes(
        spec_with(lambda d: d["api_edge"]["idempotency"].update(ttl_hours=hours))
    )


@pytest.mark.parametrize("size", [0, 1023, 1_048_577])
def test_stored_responses_are_size_capped(size: int) -> None:
    assert ("api_edge.idempotency.max_response_bytes", "invalid_value") in codes(
        spec_with(lambda d: d["api_edge"]["idempotency"].update(max_response_bytes=size))
    )


def test_idempotency_covers_only_mutating_methods_once_each() -> None:
    assert ("api_edge.idempotency.methods", "unknown_method") in codes(
        spec_with(lambda d: d["api_edge"]["idempotency"].update(methods=["GET"]))
    )
    assert ("api_edge.idempotency.methods", "unknown_method") in codes(
        spec_with(lambda d: d["api_edge"]["idempotency"].update(methods=["post"]))
    )
    assert ("api_edge.idempotency.methods", "duplicate_method") in codes(
        spec_with(lambda d: d["api_edge"]["idempotency"].update(methods=["POST", "POST"]))
    )
    assert ("api_edge.idempotency.methods", "required") in codes(
        spec_with(lambda d: d["api_edge"]["idempotency"].update(methods=[]))
    )
    assert validate(spec_with(lambda d: d["api_edge"]["idempotency"].update(methods=["POST", "PUT", "PATCH", "DELETE"]))) == []


@pytest.mark.parametrize("capacity", [0, -5, 1_000_001])
def test_bucket_capacity_must_be_in_range(capacity: object) -> None:
    assert ("api_edge.rate_limits.user.capacity", "invalid_value") in codes(
        spec_with(lambda d: d["api_edge"]["rate_limits"]["user"].update(capacity=capacity))
    )


@pytest.mark.parametrize("refill", [0, -1.0, 0.0001, 100_001.0])
def test_bucket_refill_must_be_in_range(refill: float) -> None:
    assert ("api_edge.rate_limits.anonymous.refill_per_second", "invalid_value") in codes(
        spec_with(lambda d: d["api_edge"]["rate_limits"]["anonymous"].update(refill_per_second=refill))
    )


def test_route_groups_are_checked() -> None:
    def group(**changes: object) -> Any:
        return lambda d: d["api_edge"]["rate_limits"]["groups"][0].update(**changes)

    assert ("api_edge.rate_limits.groups[0].name", "invalid_name") in codes(spec_with(group(name="Heavy Writes")))
    assert ("api_edge.rate_limits.groups[0].name", "invalid_name") in codes(spec_with(group(name="default")))
    assert ("api_edge.rate_limits.groups[0].path_prefix", "invalid_path") in codes(spec_with(group(path_prefix="orders")))
    assert ("api_edge.rate_limits.groups[0].path_prefix", "invalid_path") in codes(spec_with(group(path_prefix="/a/../b")))
    assert ("api_edge.rate_limits.groups[0].path_prefix", "invalid_path") in codes(spec_with(group(path_prefix="/a?x=1")))
    assert ("api_edge.rate_limits.groups[0].methods", "unknown_method") in codes(spec_with(group(methods=["FETCH"])))
    assert ("api_edge.rate_limits.groups[0].cost", "invalid_value") in codes(spec_with(group(cost=0)))
    # a cost above the bucket's capacity could never be served
    assert ("api_edge.rate_limits.groups[0].cost", "invalid_value") in codes(spec_with(group(cost=501)))
    assert ("api_edge.rate_limits.groups[0].cost", "invalid_value") in codes(spec_with(group(cost=1001, user=None)))

    def twice(d: dict[str, Any]) -> None:
        d["api_edge"]["rate_limits"]["groups"].append(copy.deepcopy(d["api_edge"]["rate_limits"]["groups"][0]))

    assert ("api_edge.rate_limits.groups[1].name", "duplicate") in codes(spec_with(twice))


def test_quotas_are_checked() -> None:
    def quota(**changes: object) -> Any:
        return lambda d: d["api_edge"]["quotas"][0].update(**changes)

    assert ("api_edge.quotas[0].period", "unknown_period") in codes(spec_with(quota(period="week")))
    assert ("api_edge.quotas[0].meter", "invalid_name") in codes(spec_with(quota(meter="Writes")))
    assert ("api_edge.quotas[0].limit", "invalid_value") in codes(spec_with(quota(limit=0)))
    assert ("api_edge.quotas[0].limit", "invalid_value") in codes(spec_with(quota(limit=10**13)))
    assert ("api_edge.quotas[0].cost", "invalid_value") in codes(spec_with(quota(cost=0)))
    assert ("api_edge.quotas[0].cost", "invalid_value") in codes(spec_with(quota(limit=5, cost=6)))
    assert ("api_edge.quotas[0].path_prefix", "invalid_path") in codes(spec_with(quota(path_prefix="orders")))

    def twice(d: dict[str, Any]) -> None:
        d["api_edge"]["quotas"].append(copy.deepcopy(d["api_edge"]["quotas"][0]))

    assert ("api_edge.quotas[1].meter", "duplicate") in codes(spec_with(twice))


@pytest.mark.parametrize("value", ["2026-13-01", "2026-02-30", "26-01-01", "2026-1-1", "latest", "", "2026-11-01T00:00"])
def test_versions_are_real_calendar_dates(value: str) -> None:
    def bad(d: dict[str, Any]) -> None:
        d["api_edge"]["versioning"]["versions"][0]["date"] = value

    assert ("api_edge.versioning.versions[0].date", "invalid_date") in codes(spec_with(bad))


def test_versions_have_a_known_default_and_no_duplicates() -> None:
    assert ("api_edge.versioning.default", "unknown_version") in codes(
        spec_with(lambda d: d["api_edge"]["versioning"].update(default="2020-01-01"))
    )
    assert ("api_edge.versioning.default", "invalid_date") in codes(
        spec_with(lambda d: d["api_edge"]["versioning"].update(default="newest"))
    )

    def twice(d: dict[str, Any]) -> None:
        d["api_edge"]["versioning"]["versions"].append({"date": "2026-01-15"})

    assert ("api_edge.versioning.versions[3].date", "duplicate") in codes(spec_with(twice))
    assert ("api_edge.versioning.versions", "required") in codes(
        spec_with(lambda d: d["api_edge"]["versioning"].update(versions=[], default="2026-01-01"))
    )


def test_the_tables_are_reserved_and_only_the_used_ones_exist() -> None:
    assert API_EDGE_TABLES == ("api_idempotency", "api_quota_usage", "api_rate_buckets")

    def clash(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = "api_rate_buckets"

    assert ("entities[0].table_name", "duplicate_name") in codes(spec_with(clash))
    assert api_edge_tables(spec_with()) == API_EDGE_TABLES
    only_idem = spec_with(lambda d: d["api_edge"].update(rate_limits=None, quotas=[], versioning=None))
    assert api_edge_tables(only_idem) == ("api_idempotency",)


def test_a_disabled_block_changes_nothing() -> None:
    plain = spec_with(lambda d: d.pop("api_edge"))
    off = spec_with(lambda d: d["api_edge"].update(enabled=False))
    assert generate(plain) == generate(off)
    assert not any("api_edge" in p or p == "app/hooks/api_versions.py" for p in generate(off))
    assert "api_edge" not in "".join(generate(off).values())


@pytest.mark.parametrize("name", ["blog", "numbering", "demo_leave", "library", "events_orders"])
def test_projects_without_the_block_have_no_edge_files_or_wiring(name: str) -> None:
    files = generate(Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    assert not [p for p in files if "api_edge" in p or "api_versions" in p or "0012" in p]
    assert not any("api_edge" in text or "Idempotency-Key" in text for text in files.values())


def test_an_enabled_project_gets_the_edge_files_wiring_and_a_migration() -> None:
    files = generate(spec_with())
    for path in (
        "app/api_edge/definitions.py",
        "app/api_edge/install.py",
        "app/api_edge/middleware.py",
        "app/api_edge/guard.py",
        "app/api_edge/caller.py",
        "app/api_edge/idempotency.py",
        "app/api_edge/ratelimit.py",
        "app/api_edge/quota.py",
        "app/api_edge/versioning.py",
        "app/api_edge/models.py",
        "app/api_edge/maintenance.py",
        "app/hooks/api_versions.py",
        "alembic/versions/0012_api_edge.py",
        "tests/test_api_edge.py",
    ):
        assert path in files, path
    assert "install_api_edge(app)" in files["app/main.py"]
    assert "_api_edge_models" in files["app/models/__init__.py"]
    for table in API_EDGE_TABLES:
        assert table in files["tests/conftest.py"]  # emptied between tests
        assert table in files["alembic/versions/0012_api_edge.py"]


def test_the_transformer_file_is_the_owners_and_is_listed_in_the_zone_manifest() -> None:
    files = generate(spec_with())
    zones = json.loads(files["platform/zones.json"])["zones"]
    assert zones["app/hooks/api_versions.py"] == "custom"
    assert zones["app/api_edge/middleware.py"] == "generated"
    assert zones["app/api_edge/definitions.py"] == "generated"
    assert "TRANSFORMERS: dict" in files["app/hooks/api_versions.py"]


def test_only_the_parts_that_are_on_are_generated() -> None:
    only_versions = generate(spec_with(lambda d: d["api_edge"].update(idempotency=None, rate_limits=None, quotas=[])))
    assert "app/api_edge/versioning.py" in only_versions
    assert not [p for p in only_versions if p in ("app/api_edge/guard.py", "app/api_edge/models.py", "alembic/versions/0012_api_edge.py")]
    assert "_api_edge_models" not in only_versions["app/models/__init__.py"]
    only_idem = generate(spec_with(lambda d: d["api_edge"].update(rate_limits=None, quotas=[], versioning=None)))
    assert "app/api_edge/idempotency.py" in only_idem
    assert not [p for p in only_idem if p in ("app/api_edge/ratelimit.py", "app/api_edge/quota.py", "app/api_edge/versioning.py", "app/hooks/api_versions.py")]
    assert "api_rate_buckets" not in only_idem["alembic/versions/0012_api_edge.py"]


def test_the_edge_migration_follows_the_events_migration_when_there_is_one() -> None:
    def with_events(d: dict[str, Any]) -> None:
        d["events"] = {"enabled": True, "adapter": "in_process", "retention_days": 14}

    plain = generate(spec_with())["alembic/versions/0012_api_edge.py"]
    chained = generate(spec_with(with_events))["alembic/versions/0012_api_edge.py"]
    assert 'down_revision: str | None = "0009"' in chained
    assert 'down_revision: str | None = "0009"' not in plain


def test_the_generated_code_never_stores_or_logs_a_credential() -> None:
    files = generate(spec_with())
    stored = files["app/api_edge/idempotency.py"]
    assert 'KEPT_HEADERS = ("content-type", "location")' in stored
    assert "authorization" not in files["app/api_edge/models.py"].lower().replace("never an authorization", "")
    assert "x-forwarded-for" in files["app/api_edge/caller.py"]
    assert "trusted_proxies()" in files["app/api_edge/caller.py"]


def test_generation_is_deterministic() -> None:
    assert generate(spec_with()) == generate(spec_with())


@pytest.mark.parametrize("hours", [1, 48, 168])
def test_idempotency_ttl_accepts_up_to_seven_days(hours: int) -> None:
    assert ("api_edge.idempotency.ttl_hours", "invalid_value") not in codes(
        spec_with(lambda d: d["api_edge"]["idempotency"].update(ttl_hours=hours))
    )
