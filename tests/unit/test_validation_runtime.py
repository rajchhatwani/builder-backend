"""Settings, sequences and lists validation: every way they can be wrong is reported with a path and a code."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(change: Any = None) -> Spec:
    data: dict[str, Any] = copy.deepcopy(
        json.loads((FIXTURES / "runtime_config.json").read_text(encoding="utf-8"))
    )
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def test_the_example_is_valid() -> None:
    assert validate(spec_with()) == []


def test_setting_names_must_be_clean_unique_and_not_secret_looking() -> None:
    def bad(d: dict[str, Any]) -> None:
        s = d["settings"]
        s[0]["key"] = "Bad-Key"
        s[2]["key"] = "smtp_password"
        s[3]["key"] = "api_key_for_x"

    found = codes(spec_with(bad))
    assert ("settings[0].key", "invalid_value") in found
    assert ("settings[2].key", "secret_name") in found
    assert ("settings[3].key", "secret_name") in found

    def dup(d: dict[str, Any]) -> None:
        d["settings"][1]["key"] = d["settings"][0]["key"]

    assert ("settings[1].key", "duplicate_name") in codes(spec_with(dup))


def test_defaults_must_exist_and_match_the_type_and_limits() -> None:
    def bad(d: dict[str, Any]) -> None:
        s = d["settings"]
        s[0]["default"] = "2"  # decimal above maximum 1
        s[1]["default"] = "many"  # int given text
        s[2]["default"] = "no"  # bool given text
        s[3]["default"] = "x" * 121  # longer than max_length

    found = codes(spec_with(bad))
    assert ("settings[0].default", "out_of_range") in found
    assert ("settings[1].default", "invalid_value") in found
    assert ("settings[2].default", "invalid_value") in found
    assert ("settings[3].default", "too_long") in found

    def missing(d: dict[str, Any]) -> None:
        d["settings"][0]["default"] = None
        d["settings"][1]["type"] = "float"

    found = codes(spec_with(missing))
    assert ("settings[0].default", "required") in found
    assert ("settings[1].type", "invalid_value") in found


def test_bounds_must_be_consistent_and_fit_the_type() -> None:
    def bad(d: dict[str, Any]) -> None:
        s = d["settings"]
        s[0]["minimum"], s[0]["maximum"] = "0.9", "0.1"
        s[1]["minimum"] = "ten"
        s[2]["minimum"] = 1  # bool
        s[3]["max_length"] = 0

    found = codes(spec_with(bad))
    assert ("settings[0].minimum", "invalid_value") in found
    assert ("settings[1].minimum", "invalid_value") in found
    assert ("settings[2].minimum", "invalid_value") in found
    assert ("settings[3].max_length", "invalid_value") in found

    def float_default(d: dict[str, Any]) -> None:
        d["settings"][0]["default"] = 0.5  # decimals are strings: a float never reaches validation

    with pytest.raises(ValidationError):
        spec_with(float_default)


def test_roles_must_exist_and_need_auth() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["settings"][0]["edit_roles"] = ["ghost"]
        d["sequences"][0]["view_roles"] = ["ghost"]
        d["lists"][0]["edit_roles"] = ["ghost"]

    found = codes(spec_with(bad))
    assert ("settings[0].edit_roles[0]", "unknown_role") in found
    assert ("sequences[0].view_roles[0]", "unknown_role") in found
    assert ("lists[0].edit_roles[0]", "unknown_role") in found

    def no_auth(d: dict[str, Any]) -> None:
        del d["auth"]
        d["entities"][0]["name"] = "Order"
        d["sequences"][0]["per_tenant"] = False

    found = codes(spec_with(no_auth))
    assert ("settings[0].edit_roles", "auth_required") in found
    assert ("sequences[0].view_roles", "auth_required") in found
    assert ("lists[0].edit_roles", "auth_required") in found


def test_sequences_are_checked() -> None:
    def bad(d: dict[str, Any]) -> None:
        q = d["sequences"]
        q[0]["name"] = "Bad Name"
        q[1]["name"] = "order_no"
        q[1]["prefix"] = "no spaces!"
        q[1]["padding"] = 40
        q[1]["start"] = -1

    found = codes(spec_with(bad))
    assert ("sequences[0].name", "invalid_value") in found
    assert ("sequences[1].prefix", "invalid_value") in found
    assert ("sequences[1].padding", "invalid_value") in found
    assert ("sequences[1].start", "invalid_value") in found

    def dup(d: dict[str, Any]) -> None:
        d["sequences"][1]["name"] = d["sequences"][0]["name"]

    assert ("sequences[1].name", "duplicate_name") in codes(spec_with(dup))

    def single_tenant(d: dict[str, Any]) -> None:
        d["auth"]["multi_tenant"] = False

    assert ("sequences[0].per_tenant", "tenancy_required") in codes(spec_with(single_tenant))


def test_lists_are_checked() -> None:
    def bad(d: dict[str, Any]) -> None:
        items = d["lists"][0]["items"]
        items[0]["value"] = "Bad Value"
        items[1]["value"] = items[2]["value"]
        items[2]["label"] = " "
        items[3]["color"] = "red"
        d["lists"][0]["max_items"] = 3

    found = codes(spec_with(bad))
    assert ("lists[0].items", "too_many") in found
    assert ("lists[0].items[0].value", "invalid_value") in found
    assert ("lists[0].items[2].label", "invalid_value") in found
    assert ("lists[0].items[3].color", "invalid_value") in found

    def dup(d: dict[str, Any]) -> None:
        d["lists"][0]["items"][1]["value"] = d["lists"][0]["items"][0]["value"]
        d["lists"].append(copy.deepcopy(d["lists"][0]))

    found = codes(spec_with(dup))
    assert ("lists[0].items[1].value", "duplicate_name") in found
    assert ("lists[1].name", "duplicate_name") in found

    def limits(d: dict[str, Any]) -> None:
        d["lists"][0]["max_items"] = 100000

    assert ("lists[0].max_items", "invalid_value") in codes(spec_with(limits))


def test_the_tables_are_reserved() -> None:
    def clash(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = "rc_settings"

    assert any(code == "duplicate_name" for _, code in codes(spec_with(clash)))
    # An entity may use the name when the feature is not in use.
    data = json.loads((FIXTURES / "runtime_config.json").read_text(encoding="utf-8"))
    for key in ("settings", "sequences", "lists"):
        data[key] = []
    data["entities"][0]["table_name"] = "rc_settings"
    assert validate(Spec.model_validate(data)) == []


def test_the_block_is_emitted_only_when_a_section_is_used() -> None:
    files = generate(spec_with())
    assert "alembic/versions/0006_runtime_config.py" in files
    assert 'down_revision: str | None = "0002"' in files["alembic/versions/0006_runtime_config.py"]
    data = json.loads((FIXTURES / "runtime_config.json").read_text(encoding="utf-8"))
    for key in ("settings", "sequences", "lists"):
        data[key] = []
    assert not [p for p in generate(Spec.model_validate(data)) if "runtime_config" in p]


def test_the_migration_follows_state_machines_and_the_other_blocks() -> None:
    flow = json.loads((FIXTURES / "flow_invoices.json").read_text(encoding="utf-8"))
    extra = json.loads((FIXTURES / "runtime_config.json").read_text(encoding="utf-8"))
    flow["settings"] = [extra["settings"][3]]
    flow["settings"][0]["edit_roles"] = ["admin"]
    files = generate(Spec.model_validate(flow))
    assert 'down_revision: str | None = "0005"' in files["alembic/versions/0006_runtime_config.py"]
    assert 'down_revision: str | None = "0002"' in files["alembic/versions/0005_state_machines.py"]
    flow["state_machines"] = []
    files = generate(Spec.model_validate(flow))
    assert 'down_revision: str | None = "0002"' in files["alembic/versions/0006_runtime_config.py"]
    assert "alembic/versions/0005_state_machines.py" not in files


def test_without_auth_only_reads_are_generated() -> None:
    data = json.loads((FIXTURES / "minimal.json").read_text(encoding="utf-8"))
    data["settings"] = [{"key": "page_size", "type": "int", "default": 20, "minimum": 1}]
    data["lists"] = [{"name": "colours", "items": [{"value": "red", "label": "Red"}]}]
    data["sequences"] = [{"name": "ticket", "prefix": "T-", "padding": 4}]
    files = generate(Spec.model_validate(data))
    router = files["app/runtime_config/router.py"]
    assert "@router.get(" in router and "@router.put(" not in router and "@router.delete(" not in router
    assert 'down_revision: str | None = "0001"' in files["alembic/versions/0006_runtime_config.py"]
    assert "next_number" in files["app/runtime_config/sequences.py"]
    data["settings"], data["lists"] = [], []
    assert "app/runtime_config/router.py" not in generate(Spec.model_validate(data))
