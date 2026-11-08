"""Change-history validation: every way the `history` section can be wrong is reported with a path and a code."""

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
        json.loads((FIXTURES / "history_notes.json").read_text(encoding="utf-8"))
    )
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def test_the_example_is_valid() -> None:
    assert validate(spec_with()) == []


def test_entity_must_exist_and_have_one_config() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["history"][0]["entity"] = "Ghost"
        d["history"].append(dict(d["history"][1]))

    found = codes(spec_with(bad))
    assert ("history[0].entity", "unknown_entity") in found
    assert ("history[2].entity", "duplicate") in found


def test_fields_must_exist_be_unique_and_not_secret_looking() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["history"][0]["fields"] = ["title", "title", "nope"]

    found = codes(spec_with(bad))
    assert ("history[0].fields[1]", "duplicate_name") in found
    assert ("history[0].fields[2]", "unknown_field") in found

    def secret(d: dict[str, Any]) -> None:
        for name in ("password_hash", "API_KEY", "auth_token", "client_secret"):
            d["entities"][0]["fields"].append({"name": name, "type": "string", "required": False})
        d["history"][0]["fields"] = ["password_hash", "API_KEY", "auth_token", "client_secret"]

    found = codes(spec_with(secret))
    assert {(f"history[0].fields[{k}]", "secret_name") for k in range(4)} <= found

    def none_listed(d: dict[str, Any]) -> None:
        d["history"][0]["fields"] = []

    assert ("history[0].fields", "required") in codes(spec_with(none_listed))


def test_the_state_of_a_state_machine_is_refused() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["history"][1]["fields"] = ["subject", "status"]

    assert ("history[1].fields[1]", "state_field") in codes(spec_with(bad))


@pytest.mark.parametrize("days,ok", [(0, False), (-5, False), (1, True), (3650, True), (3651, False)])
def test_retention_must_be_1_to_3650(days: int, ok: bool) -> None:
    def change(d: dict[str, Any]) -> None:
        d["history"][0]["retention_days"] = days

    assert (("history[0].retention_days", "invalid_value") not in codes(spec_with(change))) is ok


def test_retention_is_required() -> None:
    def missing(d: dict[str, Any]) -> None:
        del d["history"][0]["retention_days"]

    with pytest.raises(ValidationError):
        spec_with(missing)


def test_view_roles_must_exist_and_need_auth() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["history"][0]["view_roles"] = ["ghost"]

    assert ("history[0].view_roles[0]", "unknown_role") in codes(spec_with(bad))

    def no_auth(d: dict[str, Any]) -> None:
        d.pop("auth")
        d["state_machines"] = []
        d["history"][1]["view_roles"] = []

    found = codes(spec_with(no_auth))
    assert ("history[0].view_roles", "auth_required") in found
    assert not any(p == "history[1].view_roles" for p, _ in found)


def test_the_table_name_is_reserved() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = "ch_changes"

    assert ("entities[0].table_name", "duplicate_name") in codes(spec_with(bad))


def test_nothing_is_generated_without_the_section_and_empty_view_roles_mean_no_route() -> None:
    files = generate(spec_with())
    assert "app/change_history/hooks.py" in files and "alembic/versions/0007_change_history.py" in files
    assert "down_revision: str | None = \"0005\"" in files["alembic/versions/0007_change_history.py"]

    def bare(d: dict[str, Any]) -> None:
        d["history"] = []

    assert not [p for p in generate(spec_with(bare)) if "change_history" in p]

    def nobody(d: dict[str, Any]) -> None:
        for h in d["history"]:
            h["view_roles"] = []

    files = generate(spec_with(nobody))
    assert "app/change_history/router.py" not in files
    assert "_change_history_router" not in files["app/main.py"]


def test_only_audited_fields_are_in_the_generated_definitions() -> None:
    definitions = generate(spec_with())["app/change_history/definitions.py"]
    assert "'title'" in definitions and "'subject'" in definitions
    assert "private_note" not in definitions and "internal_memo" not in definitions
