"""The reserved `auth.suite` block: empty by default, validated when present, ignored by the generator."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.generator import generate
from app.core.spec_models import Spec, SpecSuiteRef

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _shop() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "shop_auth.json").read_text(encoding="utf-8"))
    return data


def test_suite_is_empty_by_default() -> None:
    assert Spec.model_validate(_shop()).auth.suite is None  # type: ignore[union-attr]


def test_suite_ids_are_validated() -> None:
    assert SpecSuiteRef(suite_id="acme-suite").join_state == "none"
    for bad in ("", "Acme", "a b", "-x", "x" * 64):
        with pytest.raises(ValidationError):
            SpecSuiteRef(suite_id=bad)


def test_the_generator_ignores_the_suite_block() -> None:
    plain = generate(Spec.model_validate(_shop()))
    data = _shop()
    data["auth"]["suite"] = {"suite_id": "acme", "hub_issuer": "https://hub.example/realms/a"}
    assert generate(Spec.model_validate(data)) == plain
