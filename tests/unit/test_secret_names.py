"""Secret-looking names are refused at every validation site (settings, sequences, history, seed), and
NUL / bidi control characters are refused in list labels and string setting defaults."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_runtime import looks_secret

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
NAMES = [
    "pwd", "db_pwd", "passwd", "passphrase", "pin", "user_pin", "otp", "otp_code", "cvv", "cvc", "ssn",
    "iban", "cardnumber", "card_number", "private_key", "credential", "credentials", "user_credentials",
    "password", "api_token", "client_secret",
]  # fmt: skip
FINE = ["shipping", "mapping", "spinner", "description", "optional", "topic", "invoice_footer", "pincode"]


def load(name: str, change: Any) -> list[tuple[str, str]]:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    change(data)
    return [(i.path, i.code) for i in validate(Spec.model_validate(data))]


@pytest.mark.parametrize("name", NAMES)
def test_looks_secret_catches(name: str) -> None:
    assert looks_secret(name) and looks_secret(name.upper())


@pytest.mark.parametrize("name", FINE)
def test_looks_secret_leaves_ordinary_names_alone(name: str) -> None:
    assert not looks_secret(name)


@pytest.mark.parametrize("name", NAMES)
def test_settings_refuse_secret_names(name: str) -> None:
    def change(d: dict[str, Any]) -> None:
        d["settings"][0]["key"] = name

    assert ("settings[0].key", "secret_name") in load("runtime_config", change)


@pytest.mark.parametrize("name", NAMES)
def test_sequences_refuse_secret_names(name: str) -> None:
    def change(d: dict[str, Any]) -> None:
        d["sequences"][0]["name"] = name

    assert ("sequences[0].name", "secret_name") in load("runtime_config", change)


@pytest.mark.parametrize("name", NAMES)
def test_history_refuses_secret_fields(name: str) -> None:
    def change(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"].append({"name": name, "type": "string", "required": False})
        d["history"][0]["fields"] = [name]

    assert ("history[0].fields[0]", "secret_name") in load("history_notes", change)


@pytest.mark.parametrize("name", NAMES)
def test_seed_refuses_secret_columns(name: str) -> None:
    def change(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"].append({"name": name, "type": "string", "required": False})
        plan = d["seed"][0]["entities"][0]
        plan["fields"].append({"field": name, "generator": {"type": "constant", "value": "abc"}})

    assert any(c == "secret_name" for (_p, c) in load("seed_demo", change))


@pytest.mark.parametrize("bad", ["a\x00b", "a‮b", "a⁦b", "⁩", "x‪"])
def test_list_labels_refuse_nul_and_bidi_controls(bad: str) -> None:
    def change(d: dict[str, Any]) -> None:
        d["lists"][0]["items"][0]["label"] = bad

    assert ("lists[0].items[0].label", "invalid_value") in load("runtime_config", change)


def test_html_labels_are_stored_verbatim() -> None:
    def change(d: dict[str, Any]) -> None:
        d["lists"][0]["items"][0]["label"] = "<b>New</b>"

    assert load("runtime_config", change) == []


def test_string_setting_defaults_refuse_nul() -> None:
    def change(d: dict[str, Any]) -> None:
        d["settings"][3]["default"] = "a\x00b"

    assert ("settings[3].default", "invalid_value") in load("runtime_config", change)
