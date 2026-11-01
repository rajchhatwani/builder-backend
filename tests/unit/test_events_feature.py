"""Events (outbox + event bus): the `events` block is validated, off by default (other projects are
untouched), and an enabled project gets the outbox, typed events, relay and migration."""

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_events import ADAPTERS, EV_TABLES

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(change: Any = None, name: str = "events_orders") -> Spec:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def test_the_example_is_valid() -> None:
    assert validate(spec_with()) == []


def test_unknown_adapters_are_refused_and_redis_streams_is_not_implemented_yet() -> None:
    assert ("events.adapter", "unknown_adapter") in codes(spec_with(lambda d: d["events"].update(adapter="kafka")))
    issues = [i for i in validate(spec_with(lambda d: d["events"].update(adapter="redis_streams"))) if i.path == "events.adapter"]
    assert [i.code for i in issues] == ["not_yet_implemented"]
    assert "in_process" in issues[0].message
    assert ADAPTERS == ("in_process", "redis_streams")


@pytest.mark.parametrize("value", [0, -1, 3651, 10**9])
def test_retention_must_be_in_range(value: int) -> None:
    assert ("events.retention_days", "invalid_value") in codes(spec_with(lambda d: d["events"].update(retention_days=value)))


def test_unknown_keys_and_wrong_types_are_refused_by_the_schema() -> None:
    with pytest.raises(ValueError):
        spec_with(lambda d: d["events"].update(topic="x"))
    with pytest.raises(ValueError):
        spec_with(lambda d: d["events"].update(retention_days="soon"))


def test_events_need_an_entity_and_own_their_table_names() -> None:
    def no_entities(d: dict[str, Any]) -> None:
        d["entities"], d["relations"], d["state_machines"] = [], [], []
        d["auth"] = None
    assert ("events", "no_entities") in codes(spec_with(no_entities))

    def clash(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = "ev_outbox"
    assert ("entities[0].table_name", "duplicate_name") in codes(spec_with(clash))
    assert EV_TABLES == ("ev_handled", "ev_outbox")


def test_a_disabled_block_changes_nothing() -> None:
    plain = spec_with(lambda d: d.pop("events"))
    off = spec_with(lambda d: d["events"].update(enabled=False))
    assert generate(plain) == generate(off)
    assert not any(p.startswith("app/events/") or "events" in p for p in generate(off))
    assert "ev_outbox" not in "".join(generate(off).values())


@pytest.mark.parametrize("name", ["blog", "numbering", "demo_leave", "library"])
def test_projects_without_the_block_have_no_event_files_or_wiring(name: str) -> None:
    files = generate(Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    assert not [p for p in files if p.startswith("app/events") or p.endswith("_events.py") or "0009" in p]
    assert not any("app.events" in text for text in files.values())


def test_an_enabled_project_gets_the_outbox_the_relay_and_the_wiring() -> None:
    files = generate(spec_with())
    for path in (
        "app/events/models.py", "app/events/outbox.py", "app/events/relay.py", "app/events/hooks.py",
        "app/events/types.py", "app/events/bus.py", "app/events/adapters.py", "app/events/definitions.py",
        "app/hooks/subscribers.py", "alembic/versions/0009_events.py", "tests/test_events.py",
    ):
        assert path in files, path
    assert "relay = start_relay()" in files["app/main.py"] and "await stop_relay(relay)" in files["app/main.py"]
    assert "_event_models" in files["app/models/__init__.py"]
    assert files["app/crud/orders.py"].rstrip().endswith('OrderRepository.hooks = _event_hooks.attach("Order", OrderRepository.hooks)')
    assert "ev_outbox" in files["tests/conftest.py"] and "ev_handled" in files["tests/conftest.py"]
    zones = json.loads(files["platform/zones.json"])["zones"]
    assert zones["app/hooks/subscribers.py"] == "custom" and zones["app/events/relay.py"] == "generated"


def test_the_migration_creates_the_claim_indexes_and_chains_after_the_other_blocks() -> None:
    files = generate(spec_with())
    migration = files["alembic/versions/0009_events.py"]
    assert 'op.create_index("ix_ev_outbox_claim", "ev_outbox", ["status", "next_attempt_at"])' in migration
    assert "uq_ev_outbox_aggregate_seq" in migration and "tenant_id" in migration
    revisions = {
        m.group(1): m.group(2)
        for path, text in files.items()
        if path.startswith("alembic/versions/")
        for m in [re.search(r'^revision: str = "(\w+)"\ndown_revision: str \| None = (?:"(\w+)"|None)$', text, re.M)]
        if m
    }
    assert revisions["0009"] in revisions  # follows a block that exists
    heads = set(revisions) - {v for v in revisions.values() if v}
    assert heads == {"0009"}  # one linear chain ending in the events migration


def test_without_multi_tenancy_there_is_no_tenant_column() -> None:
    def single(d: dict[str, Any]) -> None:
        d["auth"]["multi_tenant"] = False
        for p in d["auth"]["permissions"]:
            p.pop("row_rule")
    files = generate(spec_with(single))
    assert "tenant_id" not in files["app/events/models.py"]
    assert "tenant_id" not in files["alembic/versions/0009_events.py"]
    assert "MULTI_TENANT = False" in files["app/events/definitions.py"]


def test_events_work_for_a_project_without_auth_or_state_machines() -> None:
    files = generate(spec_with(name="blog", change=lambda d: d.update(events={"enabled": True})))
    assert "Transitioned" not in files["app/events/types.py"]
    assert "StateTransition" not in files["app/events/hooks.py"]
    assert "tenant_id" not in files["app/events/models.py"]


def test_payloads_leave_out_secret_looking_json_and_relation_fields() -> None:
    def extra(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"] += [
            {"name": "password_hint", "type": "string"}, {"name": "notes", "type": "json"},
            {"name": "card_number", "type": "string"}, {"name": "monkey_session_cookie", "type": "string"},
        ]
    files = generate(spec_with(extra))
    types = files["app/events/types.py"]
    for name in ("api_token", "password_hint", "notes", "card_number", "monkey_session_cookie"):
        assert name not in types and name not in files["app/events/definitions.py"], name
    assert "email: str | None" in types  # an ordinary optional field is published


def test_extra_redact_keys_from_the_spec_are_left_out_too() -> None:
    def redact(d: dict[str, Any]) -> None:
        d["observability"] = {"extra_redact_keys": ["email"]}
    files = generate(spec_with(redact))
    assert "email" not in files["app/events/types.py"]


def test_event_names_are_snake_case_per_entity() -> None:
    from app.core.generator.features.events.module import event_prefix

    assert event_prefix("Order") == "order"
    assert event_prefix("LeaveRequest") == "leave_request"
    assert event_prefix("HTTPLog") == "httplog"


def test_the_redis_streams_adapter_ships_as_a_stub() -> None:
    adapters = generate(spec_with())["app/events/adapters.py"]
    assert "class RedisStreamsAdapter" in adapters and "not implemented yet" in adapters
    assert "class EventAdapter(Protocol)" in adapters


@pytest.mark.parametrize(
    "name",
    [
        "access_key", "accessKey", "signing_key", "SigningKey", "secret_key", "private_key", "salt", "password_salt",
        "totp", "totp_secret", "otp", "credit_card", "creditCardNo", "card_number", "pan", "cvv", "iban", "ssn",
        "passcode", "pin", "auth", "auth_header", "bearer", "cookie", "session", "sessionId", "session_ids", "seed",
        "api_token",
    ],
)  # fmt: skip
def test_the_payload_secret_filter_is_pattern_based_and_catches_the_sentinel_list(name: str) -> None:
    from app.core.generator.features.events.module import _secret_name

    assert _secret_name(name, ()), name


@pytest.mark.parametrize("name", ["title", "status", "shipping_address", "opinion", "total", "reference", "panel"])
def test_the_payload_secret_filter_keeps_ordinary_names(name: str) -> None:
    from app.core.generator.features.events.module import _secret_name

    assert not _secret_name(name, ()), name


def test_the_readme_explains_upgrading_a_deployed_project_only_when_a_migration_feature_is_on() -> None:
    with_events = generate(spec_with())["README.md"]
    assert "### Upgrading a deployed project" in with_events and "LOWER" in with_events
    plain = generate(Spec.model_validate_json((FIXTURES / "blog.json").read_text(encoding="utf-8")))["README.md"]
    assert "Upgrading a deployed project" not in plain


def test_the_delete_path_locks_the_row_and_the_handled_markers_outlive_the_retention() -> None:
    files = generate(spec_with())
    assert "with_for_update()" in files["app/events/hooks.py"]
    assert "2 * days" in files["app/events/outbox.py"]
