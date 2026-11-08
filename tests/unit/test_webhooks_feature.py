"""Webhooks (webhooks out and in): the `webhooks` block is validated (default deny, nothing secret in the spec,
the blocks it stands on must be on), off by default (other projects are untouched), and an enabled project gets
the guard, signing, vault-backed secrets, fan-out, delivery, API and migration."""

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_webhooks import FORBIDDEN_PORTS, WEBHOOK_TABLES

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(change: Any = None, name: str = "webhooks_orders") -> Spec:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def test_the_example_is_valid() -> None:
    assert validate(spec_with()) == []


@pytest.mark.parametrize(
    ("block", "code"),
    [("events", "needs_events"), ("providers", "needs_providers"), ("jobs", "needs_jobs")],
)
def test_the_blocks_webhooks_stand_on_must_be_enabled(block: str, code: str) -> None:
    def off(d: dict[str, Any]) -> None:
        d[block]["enabled"] = False

    assert ("webhooks", code) in codes(spec_with(off))


def test_auth_and_the_delivery_job_are_required() -> None:
    assert ("webhooks", "needs_auth") in codes(spec_with(lambda d: d["auth"].update(enabled=False)))
    assert ("webhooks", "needs_delivery_job") in codes(
        spec_with(lambda d: d["jobs"].update(jobs=[j for j in d["jobs"]["jobs"] if j["name"] != "webhook_delivery"]))
    )

    def wrong_handler(d: dict[str, Any]) -> None:
        next(j for j in d["jobs"]["jobs"] if j["name"] == "webhook_delivery")["handler"] = "other"

    assert ("jobs.jobs", "webhook_job_handler") in codes(spec_with(wrong_handler))

    def short_timeout(d: dict[str, Any]) -> None:
        next(j for j in d["jobs"]["jobs"] if j["name"] == "webhook_delivery")["timeout_seconds"] = 5

    assert ("jobs.jobs", "webhook_job_timeout") in codes(spec_with(short_timeout))
    assert ("webhooks.admin_role", "unknown_role") in codes(spec_with(lambda d: d["webhooks"].update(admin_role="nobody")))


def test_events_must_exist_and_are_listed_once() -> None:
    assert ("webhooks.events[0]", "unknown_event") in codes(spec_with(lambda d: d["webhooks"].update(events=["order.nonsense"])))
    assert ("webhooks.events[1]", "duplicate_event") in codes(
        spec_with(lambda d: d["webhooks"].update(events=["order.created", "order.created"]))
    )
    assert ("webhooks.events[0]", "unknown_event") in codes(spec_with(lambda d: d["webhooks"].update(events=["customer.transitioned"])))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timeout_seconds", 0), ("timeout_seconds", 61), ("max_consecutive_failures", 0), ("max_consecutive_failures", 101),
        ("secret_overlap_hours", 0), ("secret_overlap_hours", 721), ("max_payload_bytes", 10), ("max_payload_bytes", 10**8),
    ],
)
def test_limits_must_be_in_range(field: str, value: int) -> None:
    assert (f"webhooks.{field}", "invalid_value") in codes(spec_with(lambda d: d["webhooks"].update({field: value})))


def test_ports_cannot_name_internal_services() -> None:
    for port in (22, 5432, 6379, 2375, 9200):
        assert port in FORBIDDEN_PORTS
        assert ("webhooks.allowed_ports[0]", "forbidden_port") in codes(spec_with(lambda d, p=port: d["webhooks"].update(allowed_ports=[p])))
    assert ("webhooks.allowed_ports[0]", "invalid_value") in codes(spec_with(lambda d: d["webhooks"].update(allowed_ports=[0])))
    assert validate(spec_with(lambda d: d["webhooks"].update(allowed_ports=[443, 8443]))) == []


def test_incoming_endpoints_are_checked() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["webhooks"]["inbound"] = [
            {"name": "Bad Name"}, {"name": "ok_one", "tolerance_seconds": 5}, {"name": "ok_one", "max_body_bytes": 1},
            {"name": "ok_two", "dedupe_days": 0},
        ]

    found = codes(spec_with(bad))
    assert ("webhooks.inbound[0].name", "invalid_name") in found
    assert ("webhooks.inbound[1].tolerance_seconds", "invalid_value") in found
    assert ("webhooks.inbound[2].name", "duplicate_name") in found and ("webhooks.inbound[2].max_body_bytes", "invalid_value") in found
    assert ("webhooks.inbound[3].dedupe_days", "invalid_value") in found


def test_unknown_keys_are_refused_by_the_schema_and_no_secret_field_exists() -> None:
    with pytest.raises(ValueError):
        spec_with(lambda d: d["webhooks"].update(secret="whsec_abc"))
    with pytest.raises(ValueError):
        spec_with(lambda d: d["webhooks"]["inbound"][0].update(secret="x"))


def test_webhooks_own_their_table_names() -> None:
    def clash(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = "wh_deliveries"

    assert ("entities[0].table_name", "duplicate_name") in codes(spec_with(clash))
    assert WEBHOOK_TABLES == ("wh_attempts", "wh_deliveries", "wh_endpoints", "wh_inbound", "wh_subscriptions")


def test_a_disabled_block_changes_nothing() -> None:
    plain = spec_with(lambda d: d.pop("webhooks"))
    off = spec_with(lambda d: d["webhooks"].update(enabled=False))
    assert generate(plain) == generate(off)
    assert not any("webhooks" in p for p in generate(off))


@pytest.mark.parametrize("name", ["blog", "events_orders", "jobs_invoices", "providers_notify", "combined_async"])
def test_projects_without_the_block_have_no_webhook_files_or_wiring(name: str) -> None:
    files = generate(Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    assert not [p for p in files if "webhooks" in p or "0017" in p]
    assert not any("app.webhooks" in text for text in files.values())


def test_an_enabled_project_gets_the_guard_the_signing_and_the_wiring() -> None:
    files = generate(spec_with())
    for path in (
        "app/webhooks/ssrf.py", "app/webhooks/egress.py", "app/webhooks/signing.py", "app/webhooks/secrets.py",
        "app/webhooks/fanout.py", "app/webhooks/delivery.py", "app/webhooks/worker_job.py", "app/webhooks/router.py",
        "app/webhooks/handlers.py", "app/webhooks/models.py", "app/webhooks/definitions.py", "app/hooks/webhooks.py",
        "alembic/versions/0017_webhooks.py", "tests/test_webhooks.py", "tests/_webhooks_support.py",
    ):
        assert path in files, path
    assert "app.include_router(_webhooks_router)" in files["app/main.py"] and "_webhooks_public_router" in files["app/main.py"]
    assert "_webhook_models" in files["app/models/__init__.py"]
    assert 'importlib.import_module("app.webhooks.fanout")' in files["app/events/bus.py"]
    assert "from app.webhooks import worker_job" in files["app/hooks/jobs.py"] and "def webhook_delivery" not in files["app/hooks/jobs.py"]
    assert all(t in files["tests/conftest.py"] for t in WEBHOOK_TABLES)
    zones = json.loads(files["platform/zones.json"])["zones"]
    assert zones["app/hooks/webhooks.py"] == "custom" and zones["app/webhooks/ssrf.py"] == "generated"


def test_the_definitions_hold_no_secret_and_only_the_listed_events() -> None:
    files = generate(spec_with())
    text = files["app/webhooks/definitions.py"]
    assert "whsec_" not in text and "'order.created'" in text and "order.deleted" not in text
    assert "ALLOW_HTTP = False" in text and "MAX_CONSECUTIVE_FAILURES = 3" in text
    assert "payments" in text


def test_nothing_generated_follows_redirects_or_uses_a_second_resolution() -> None:
    files = generate(spec_with())
    egress = files["app/webhooks/egress.py"]
    assert "follow_redirects" not in egress and "httpx" not in egress and "getaddrinfo" not in egress
    assert files["app/webhooks/ssrf.py"].count("getaddrinfo") == 1


def test_the_migration_chains_after_the_other_blocks_and_is_the_head() -> None:
    files = generate(spec_with())
    revisions = {
        m.group(1): m.group(2)
        for path, text in files.items()
        if path.startswith("alembic/versions/")
        for m in [re.search(r'^revision: str = "(\w+)"\ndown_revision: str \| None = (?:"(\w+)"|None)$', text, re.M)]
        if m
    }
    assert revisions["0017"] in revisions
    assert set(revisions) - {v for v in revisions.values() if v} == {"0017"}
    assert "ondelete=\"CASCADE\"" in files["alembic/versions/0017_webhooks.py"]


def test_a_single_tenant_project_has_no_tenant_path() -> None:
    def single(d: dict[str, Any]) -> None:
        d["auth"]["multi_tenant"] = False
        for p in d["auth"]["permissions"]:
            p.pop("row_rule")

    files = generate(spec_with(single))
    assert "MULTI_TENANT = False" in files["app/webhooks/definitions.py"]
    assert "/in/{name}/{tenant_id}" in files["app/webhooks/router.py"]  # the template holds both; the flag picks one
