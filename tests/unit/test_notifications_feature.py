"""Notifications (email / SMS / push over the provider adapters): the `notifications` block is validated,
off by default (other projects are untouched), fails closed on bad templates and recipients, and an
enabled project gets the dispatcher, templates, preferences, delivery log, migration and tests."""

import ast
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_notifications import NOTIFICATION_TABLES, template_problem

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
NAME = "notifications_orders"


def spec_with(change: Any = None, name: str = NAME) -> Spec:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def test_the_example_is_valid() -> None:
    assert validate(spec_with()) == []


def test_the_block_is_off_by_default_and_other_projects_get_no_notification_files() -> None:
    for spec in (spec_with(lambda d: d.update(notifications=None)), spec_with(lambda d: d["notifications"].update(enabled=False))):
        files = generate(spec)
        assert not [p for p in files if "notification" in p]
        assert not any("app.notifications" in text for text in files.values())
    assert not [p for p in generate(spec_with(name="providers_notify")) if "notification" in p]


def test_the_schema_refuses_unknown_keys() -> None:
    with pytest.raises(ValueError):
        spec_with(lambda d: d["notifications"].update(api_key="x"))
    with pytest.raises(ValueError):
        spec_with(lambda d: d["notifications"]["types"][0].update(script="x"))


def test_it_needs_auth_providers_and_a_known_admin_role() -> None:
    assert ("notifications", "needs_providers") in codes(spec_with(lambda d: d.update(providers=None)))
    assert ("notifications", "needs_auth") in codes(spec_with(lambda d: d.update(auth=None)))
    assert ("notifications.admin_role", "unknown_role") in codes(spec_with(lambda d: d["notifications"].update(admin_role="nobody")))


@pytest.mark.parametrize(
    "template",
    ["{{ 7*7 }}", "{{ name.x }}", "{{ name|upper }}", "{% if name %}x{% endif %}", "{{ name }", "}}", "{# c #}", "{{ other }}", "{{ __class__ }}"],
)
def test_templates_may_only_use_declared_placeholders(template: str) -> None:
    assert template_problem(template, {"name"}) is not None
    spec = spec_with(lambda d: d["notifications"]["types"][0]["templates"][0].update(body=template))
    assert ("notifications.types[0].templates[0].body", "invalid_template") in codes(spec)


def test_declared_placeholders_pass() -> None:
    assert template_problem("Hello {{ name }} and {{name}}", {"name"}) is None


def test_template_rules() -> None:
    def bad(d: dict[str, Any]) -> None:
        t = d["notifications"]["types"][1]  # email + sms + push
        t["templates"][0]["subject"] = "Line one\nBcc: evil@example.com"
        t["templates"][1]["subject"] = "an SMS has no subject"
        t["templates"][1]["html"] = True
        t["templates"][2]["subject"] = ""
        t["templates"][2]["body"] = "  "

    found = codes(spec_with(bad))
    assert ("notifications.types[1].templates[0].subject", "invalid_value") in found
    assert ("notifications.types[1].templates[1].subject", "invalid_value") in found
    assert ("notifications.types[1].templates[1].html", "invalid_value") in found
    assert ("notifications.types[1].templates[2].subject", "empty_template") in found
    assert ("notifications.types[1].templates[2].body", "empty_template") in found


def test_every_channel_needs_a_default_template() -> None:
    spec = spec_with(lambda d: d["notifications"]["types"][1].update(templates=d["notifications"]["types"][1]["templates"][:1]))
    assert ("notifications.types[1].templates", "missing_template") in codes(spec)


def test_types_channels_and_numbers_are_checked() -> None:
    def bad(d: dict[str, Any]) -> None:
        n = d["notifications"]
        n["types"][0]["channels"] = ["email", "email", "fax"]
        n["types"][1]["name"] = "Bad Name"
        n["types"][2]["name"] = "welcome"
        n["types"][2]["category"] = "sometimes"
        n["max_attempts"] = 0
        n["backoff_seconds"] = 0
        n["retention_days"] = 99999

    found = codes(spec_with(bad))
    assert ("notifications.types[0].channels", "duplicate_channel") in found
    assert ("notifications.types[0].channels", "unknown_channel") in found
    assert ("notifications.types[1].name", "invalid_name") in found
    assert ("notifications.types[2].name", "duplicate_name") in found
    assert ("notifications.types[2].category", "invalid_value") in found
    assert {("notifications.max_attempts", "invalid_value"), ("notifications.backoff_seconds", "invalid_value"), ("notifications.retention_days", "invalid_value")} <= found


def test_no_types_and_secret_looking_content_are_refused() -> None:
    assert ("notifications.types", "no_types") in codes(spec_with(lambda d: d["notifications"].update(types=[])))
    spec = spec_with(lambda d: d["notifications"]["types"][0]["variables"].append("api_token"))
    assert ("notifications.types[0].variables", "secret_in_spec") in codes(spec)
    spec = spec_with(lambda d: d["notifications"]["types"][0]["templates"][0].update(body="key sk_" "live_abcdefgh12345678 {{ name }}"))
    assert ("notifications.types[0].templates[0].body", "secret_in_spec") in codes(spec)


def test_event_triggers_are_checked() -> None:
    def bad(d: dict[str, Any]) -> None:
        t = d["notifications"]["types"][0]
        t.update(on_event="nothing.created", recipient_key_field="id")

    assert ("notifications.types[0].on_event", "unknown_event") in codes(spec_with(bad))
    assert ("notifications.types[0].on_event", "unknown_event") in codes(
        spec_with(lambda d: d["notifications"]["types"][0].update(on_event="customer.exploded"))
    )

    def fields(d: dict[str, Any]) -> None:
        t = d["notifications"]["types"][0]
        t.update(recipient_key_field="api_token", address_fields={"email": "nope", "sms": "email"})

    found = codes(spec_with(fields))
    assert ("notifications.types[0].recipient_key_field", "unknown_field") in found
    assert ("notifications.types[0].address_fields.email", "unknown_field") in found
    assert ("notifications.types[0].address_fields.sms", "unknown_channel") in found

    assert ("notifications.types[0].recipient_key_field", "missing_field") in codes(
        spec_with(lambda d: d["notifications"]["types"][0].update(recipient_key_field=None))
    )
    assert ("notifications.types[0].address_fields", "missing_address_field") in codes(
        spec_with(lambda d: d["notifications"]["types"][0].update(address_fields={}))
    )
    assert ("notifications.types[0].on_event", "needs_events") in codes(spec_with(lambda d: d.update(events=None)))
    assert ("notifications.types[1].on_event", "missing_event") in codes(
        spec_with(lambda d: d["notifications"]["types"][1].update(recipient_key_field="id"))
    )


def test_table_names_cannot_collide_with_an_entity() -> None:
    def clash(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = NOTIFICATION_TABLES[0]

    assert ("entities[0].table_name", "duplicate_name") in codes(spec_with(clash))


def test_an_enabled_project_gets_the_feature_files() -> None:
    files = generate(spec_with())
    for path in (
        "app/notifications/definitions.py", "app/notifications/render.py", "app/notifications/service.py",
        "app/notifications/dispatcher.py", "app/notifications/router.py", "app/notifications/models.py",
        "app/notifications/triggers.py", "alembic/versions/0021_notifications.py", "tests/test_notifications.py",
    ):
        assert path in files, path
        if path.endswith(".py"):
            ast.parse(files[path])
    assert "from app.notifications.router import router" in files["app/main.py"]
    assert "start_dispatcher()" in files["app/main.py"] and "stop_relay(relay)" in files["app/main.py"]
    assert "_notification_models" in files["app/models/__init__.py"]
    assert "app.notifications.triggers" in files["app/hooks/subscribers.py"]
    assert "nt_deliveries" in files["tests/conftest.py"]
    zones = json.loads(files["platform/zones.json"])["zones"]
    assert zones["app/notifications/service.py"] == "generated" and zones["app/hooks/subscribers.py"] == "custom"
    assert "NOTIFICATIONS_DISPATCHER_ENABLED" in files["app/notifications/config.py"]


def test_without_event_types_there_are_no_triggers_and_the_subscribers_stub_is_plain() -> None:
    def plain(d: dict[str, Any]) -> None:
        t = d["notifications"]["types"][0]
        t.update(on_event=None, recipient_key_field=None, address_fields={})

    files = generate(spec_with(plain))
    assert "app/notifications/triggers.py" not in files
    assert "notifications" not in files["app/hooks/subscribers.py"]


def test_no_template_is_evaluated_by_the_generated_renderer() -> None:
    source = generate(spec_with())["app/notifications/render.py"]
    assert "jinja" not in source.lower() and "eval(" not in source and "exec(" not in source
    assert "format(" not in source and "Template(" not in source


def test_definitions_hold_no_secret_and_match_the_spec() -> None:
    files = generate(spec_with())
    namespace: dict[str, Any] = {}
    exec(files["app/notifications/definitions.py"], namespace)  # noqa: S102 - plain data generated by us
    assert namespace["TYPES"]["welcome"]["on_event"] == "customer.created"
    assert namespace["TYPES"]["security_alert"]["category"] == "transactional"
    assert namespace["MAX_ATTEMPTS"] == 3 and namespace["ADMIN_ROLE"] == "admin"


def test_a_nul_character_in_a_template_is_refused() -> None:
    spec = spec_with(lambda d: d["notifications"]["types"][0]["templates"][0].update(body="Hi \u0000 {{ name }}"))
    assert ("notifications.types[0].templates[0].body", "invalid_value") in codes(spec)
    spec = spec_with(lambda d: d["notifications"]["types"][0]["templates"][0].update(subject="Hi \u0000"))
    assert ("notifications.types[0].templates[0].subject", "invalid_value") in codes(spec)


def test_the_renderer_neutralises_dangerous_url_schemes_and_the_dispatcher_caps_attempts() -> None:
    files = generate(spec_with())
    assert "safe_url" in files["app/notifications/render.py"] and '"abandoned"' in files["app/notifications/dispatcher.py"]
