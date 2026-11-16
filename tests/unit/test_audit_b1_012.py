"""Audit B1-012: render cost, reconciliation close, tolerance sign, url.query, eta range."""

import importlib.machinery
import importlib.util
import json
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec

ROOT = Path(__file__).resolve().parent.parent
FEATURES = ROOT.parent / "app" / "core" / "generator" / "features"


def _load(rel: str, name: str) -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(name, str(FEATURES / rel))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


def _generated(fixture: str) -> dict[str, str]:
    raw = json.loads((ROOT / "fixtures" / "specs" / f"{fixture}.json").read_text(encoding="utf-8"))
    return generate(Spec.model_validate(raw))


RENDER = "notifications/templates/app/notifications/render.py.tpl"


def test_f0364_html_render_is_linear() -> None:
    render = _load(RENDER, "b1_012_render")
    body = "<p>" + "{{a}}" * 10000 + "</p>"
    start = time.perf_counter()
    out = render._substitute(body, {"a": "x"}, str, urls=True)
    assert time.perf_counter() - start < 1.0
    assert out.count("x") == 10000


def test_f0364_url_attrs_still_sanitised() -> None:
    render = _load(RENDER, "b1_012_render2")
    values = {"a": "javascript:alert(1)"}
    sub = render._substitute
    assert sub('<a href="{{a}}">', values, str, urls=True) == '<a href="#">'
    assert sub("<a href='x{{a}}'>", values, str, urls=True) == "<a href='x#'>"
    assert sub("<a href={{a}}>", values, str, urls=True) == "<a href=#>"
    assert (
        sub('<a href="u">{{a}}</a>', values, str, urls=True)
        == '<a href="u">javascript:alert(1)</a>'
    )
    assert sub('<a title="t" href="{{a}}">', values, str, urls=True) == '<a title="t" href="#">'


def test_f0364_placeholder_cap() -> None:
    render = _load(RENDER, "b1_012_render3")
    with pytest.raises(render.RenderError):
        render.check_template("{{a}}" * 501, {"a"})
    render.check_template("{{a}}" * 500, {"a"})


def test_f0365_close_refuses_truncated_entries() -> None:
    files = _generated("money_marketplace")
    src = files["app/money/reconciliation/service.py"]
    close = src[src.index("async def close_run") :]
    close = close[: close.index("\nasync def ", 10)] if "\nasync def " in close[10:] else close
    assert "picture.entries_truncated" in close
    assert '"entries_truncated"' in close and "422" in close
    assert close.index("entries_truncated") < close.index('run.status = "closed"')


def test_f0366_tolerance_requires_same_sign() -> None:
    matcher = _load(
        "money_reconciliation/templates/app/money/reconciliation/matcher.py.tpl", "b1_012_matcher"
    )
    day = date(2026, 1, 1)
    item = matcher.Item
    assert matcher.match([item("L", day, 3, None, 1)], [item("E", day, -2, None, 0)], 5) == []
    assert matcher.match([item("L", day, -3, None, 1)], [item("E", day, 2, None, 0)], 5) == []
    same = matcher.match([item("L", day, 3, None, 1)], [item("E", day, 1, None, 0)], 5)
    assert [p.method for p in same] == ["tolerance"]
    neg = matcher.match([item("L", day, -3, None, 1)], [item("E", day, -1, None, 0)], 5)
    assert [p.method for p in neg] == ["tolerance"]


def test_f0367_url_query_masked() -> None:
    src = (FEATURES / "observability/templates/app/core/telemetry.py.j2").read_text(
        encoding="utf-8"
    )
    start = src.index("_QUERY_VALUE_RE =")
    ns: dict[str, object] = {"re": __import__("re")}

    class _Redact:
        REDACTED = "[REDACTED]"

        @staticmethod
        def is_secret_key(key: str) -> bool:
            return False

        @staticmethod
        def scrub_text(text: str) -> str:
            return text

    ns["redact"] = _Redact
    ns["Sequence"] = __import__("collections.abc").abc.Sequence
    ns["Any"] = object
    code = src[start : src.index("_TRUE =")]
    code += src[src.index("def mask_query") : src.index("def clean_attributes")]
    code = code.replace("{{", "{").replace("}}", "}")
    exec(code, ns)  # noqa: S102
    clean = ns["_clean_value"]
    assert "abc123" not in clean("url.query", "token=abc123&x=1")  # type: ignore[operator]
    assert clean("url.query", "token=abc123&x=1").startswith("token=")  # type: ignore[operator]
    assert "abc" not in clean("url.full", "http://h/p?token=abc")  # type: ignore[operator]


def test_f0368_eta_depart_range() -> None:
    import types

    from pydantic import BaseModel

    class _Point(BaseModel):
        pass

    saved = {k: sys.modules.get(k) for k in ("app.operations", "app.operations.points")}
    pkg = types.ModuleType("app.operations")
    pkg.__path__ = []  # type: ignore[attr-defined]
    points = types.ModuleType("app.operations.points")
    points.Point = _Point  # type: ignore[attr-defined]
    points.PointOut = _Point  # type: ignore[attr-defined]
    sys.modules["app.operations"] = pkg
    sys.modules["app.operations.points"] = points
    try:
        schemas = _load("operations_geo/templates/app/operations/geo/schemas.py.tpl", "b1_012_geo")
        check = schemas.EtaIn._depart_in_range
        assert check(None) is None
        assert check(datetime.now(UTC) + timedelta(days=30)) is not None
        with pytest.raises(ValueError):
            check(datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC))
        with pytest.raises(ValueError):
            check(datetime(1, 1, 1))
    finally:
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old


def test_f0369_grid_cell_is_documented_as_fixed() -> None:
    text = (FEATURES / "operations_geo/templates/app/operations/geo/config.py.j2").read_text(
        encoding="utf-8"
    )
    assert "FIXED once places exist" in text
