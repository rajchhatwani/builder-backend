"""Audit B1-019 regressions: hook gate match classes, access diff for policies, limiter cap,
import coercion bounds and document engine validation."""

import base64
import copy
import io
import time

import pytest
from PIL import Image

from app.core import doc_engine as de
from app.core.access_layers import access_matrix, weakens
from app.core.data_import import coerce
from app.core.ratelimit import SlidingWindowLimiter
from app.core.spec_models import SpecField
from tests.unit.test_access_layers import base, cell, spec
from tests.unit.test_hook_gates import check


# F-0174
def test_match_class_keyword_cannot_reach_dunders() -> None:
    body = (
        "from collections.abc import Callable\n"
        "def h() -> int:\n    return 0\n"
        "match h:\n    case Callable(__globals__=g):\n        pass\n"
        "return MatchResult(allowed=True)"
    )
    assert check(body)


def test_match_class_keyword_private_and_plain_names() -> None:
    bad = "match 1:\n    case int(_x=g):\n        pass\nreturn MatchResult(allowed=True)"
    assert check(bad)


# F-0175 / F-0176
def _abac(allow_when: dict, deny: bool) -> dict:
    raw = copy.deepcopy(base())
    raw["auth"]["permissions"] = []
    pols = [{"id": "own", "effect": "allow", "actions": ["*"], "when": allow_when}]
    if deny:
        pols.append(
            {
                "id": "nosal",
                "effect": "deny",
                "actions": ["*"],
                "when": {"left": {"resource": "salary"}, "op": "eq", "right": {"literal": "high"}},
            }
        )
    raw["authorization"] = {"model": "abac", "policies": pols}
    return raw


def test_abac_deny_removed_and_allow_widened_is_a_weakening() -> None:
    eq = {"left": {"resource": "name"}, "op": "eq", "right": {"subject": "email"}}
    ne = {"left": {"resource": "name"}, "op": "ne", "right": {"literal": "x"}}
    before = spec(_abac(eq, True))
    after = spec(_abac(ne, False))
    assert weakens(before, after)
    assert not weakens(before, before)


def test_public_has_no_access_under_abac() -> None:
    eq = {"left": {"resource": "name"}, "op": "eq", "right": {"subject": "email"}}
    m = access_matrix(spec(_abac(eq, False)))
    assert cell(m, "object", "list", "(public)") == "no"


# F-0177
def test_limiter_is_capped_and_cheap() -> None:
    lim = SlidingWindowLimiter(3, 60, max_keys=100)
    for i in range(1000):
        assert lim.allow(f"k{i}")
    assert len(lim._hits) <= 100
    start = time.perf_counter()
    for i in range(2000):
        lim.allow(f"z{i}")
    assert time.perf_counter() - start < 0.5
    assert lim.allow("z1999") and lim.allow("z1999") and not lim.allow("z1999")


# F-0178
def test_import_coercion_never_raises_raw_errors() -> None:
    f = SpecField(name="n", type="bigint")
    with pytest.raises(ValueError, match="out_of_range"):
        coerce("1" * 5000, f)
    d = SpecField(name="d", type="datetime")
    with pytest.raises(ValueError, match="invalid_datetime"):
        coerce("0001-01-01T00:00:00+01:00", d)


def test_csv_template_has_the_same_guards() -> None:
    from pathlib import Path

    text = Path("app/core/generator/features/data_import/templates/app/imports/csv_import.py.tpl").read_text()
    assert "except OverflowError" in text or "OverflowError" in text
    assert "more digits than Python converts" in text


# F-0179
def test_huge_line_total_is_a_document_error() -> None:
    with pytest.raises(de.DocumentError):
        de.compute_totals(
            {"currency": "USD", "items": [{"quantity": "1000000000000", "unit_price": "100000000000000"}]}
        )


# F-0180
def _col(**over: object) -> dict:
    return {"blocks": [{"type": "table", "source": "items", "columns": [{"header": "a", "value": "x", **over}]}]}


def _png_junk() -> str:
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"junk" * 10).decode()


def _png_ok() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.mark.parametrize(
    "template",
    [
        _col(width="wide"),
        _col(width=True),
        {"blocks": [{"type": "qr", "value": "x", "size_mm": "big"}]},
        {"blocks": [{"type": "image", "data_base64": "x", "align": "top"}]},
        {"blocks": [{"type": "image", "data_base64": _png_junk()}]},
    ],
)
def test_bad_template_values_are_validation_problems(template: dict) -> None:
    assert de.validate_template(template)
    with pytest.raises(de.DocumentError):
        de.render_pdf(template, {"items": [{}]})


def test_good_image_still_renders() -> None:
    t = {"blocks": [{"type": "image", "data_base64": _png_ok(), "align": "center"}]}
    assert de.validate_template(t) == []
    assert de.render_pdf(t, {}).startswith(b"%PDF")
