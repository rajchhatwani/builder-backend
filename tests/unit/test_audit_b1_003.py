"""Audit B1-003: metrics/realtime prefixes reserved (F-0922); column range and rate-limit regex tests (F-0925)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _fx(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _codes(d: dict[str, Any]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(Spec.model_validate(d))}


@pytest.mark.parametrize("path", ["metrics", "realtime"])
def test_f0922_entity_path_cannot_shadow_metrics_or_realtime(path: str) -> None:
    d = _fx("realtime_metrics.json")
    d["entities"][0]["plural_path"] = path
    codes = _codes(d)
    assert ("entities[0].plural_path", "reserved_word") in codes or ("entities[0].plural_path", "duplicate_name") in codes


def _with_field(**extra: Any) -> dict[str, Any]:
    d = _fx("blog.json")
    d["entities"][0]["fields"].append({"name": "qty_probe", "required": False, **extra})
    return d


def _field_codes(d: dict[str, Any]) -> set[str]:
    n = len(d["entities"][0]["fields"]) - 1
    return {c for p, c in _codes(d) if p.startswith(f"entities[0].fields[{n}]")}


def test_f0925_integer_bounds() -> None:
    assert "out_of_range" in _field_codes(_with_field(type="integer", max_value=2**31))
    assert "out_of_range" not in _field_codes(_with_field(type="integer", max_value=2**31 - 1))
    assert "out_of_range" in _field_codes(_with_field(type="bigint", max_value=2**63))
    assert "out_of_range" in _field_codes(_with_field(type="decimal", max_value=10**13))
    assert "invalid_range" in _field_codes(_with_field(type="integer", min_value=0.2, max_value=0.8))
    assert "invalid_range" not in _field_codes(_with_field(type="integer", min_value=0.2, max_value=1.5))


@pytest.mark.parametrize("value", ["0/minute", "05/minute", "5/0minutes", "5/minute "])
def test_f0925_auth_rate_limit_regex(value: str) -> None:
    d = _fx("realtime_metrics.json")
    d["auth"]["login_rate_limit"] = value
    assert ("auth.login_rate_limit", "invalid_value") in _codes(d)
    d["auth"]["login_rate_limit"] = "5/15minutes"
    assert ("auth.login_rate_limit", "invalid_value") not in _codes(d)


@pytest.mark.parametrize("value", ["0/minute", "05/minute", "5/0minutes"])
def test_f0925_documents_rate_limit_regex(value: str) -> None:
    from app.core.validation_documents import RATE_RE

    assert RATE_RE.fullmatch(value) is None
    assert RATE_RE.fullmatch("30/minute") and RATE_RE.fullmatch("5/15minutes")
