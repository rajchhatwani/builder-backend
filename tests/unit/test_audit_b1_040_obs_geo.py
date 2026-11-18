"""Audit B1-040: excluded-URL anchor, per-signal OTLP gate, denial counter at the denial site, query-key test, nearest scan."""

import ast
import asyncio
import json
import re
import types
from pathlib import Path
from typing import Any

from app.core.generator import generate
from app.core.spec_models import Spec

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _files(name: str) -> dict[str, str]:
    return generate(Spec.model_validate(json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))))


def _funcs(source: str, names: set[str], ns: dict[str, Any]) -> dict[str, Any]:
    tree = ast.parse(source)
    body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.Module(body=body, type_ignores=[]), "gen", "exec"), ns)  # noqa: S102
    return ns


def test_f1181_excluded_pattern_ignores_paths_inside_the_query() -> None:
    src = _files("obs_blog")["app/core/telemetry.py"]
    ns = _funcs(src, {"_excluded_urls_pattern"}, {"re": re, "EXCLUDED_PATHS": ("/health",)})
    pattern = ns["_excluded_urls_pattern"]()
    assert re.search(pattern, "http://h:8000/health")
    assert re.search(pattern, "http://h/health?x=1")
    assert re.search(pattern, "/health")
    assert not re.search(pattern, "http://h/a?next=http://x/health")
    assert not re.search(pattern, "http://h/a?next=/health")


def test_f1182_traces_and_metrics_endpoints_gate_separately(monkeypatch: Any) -> None:
    src = _files("obs_blog")["app/core/telemetry.py"]
    import os

    ns = _funcs(src, {"_endpoint_configured"}, {"os": os})
    for name in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://c:4318/v1/traces")
    assert ns["_endpoint_configured"]("TRACES")
    assert not ns["_endpoint_configured"]("METRICS")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://c:4318")
    assert ns["_endpoint_configured"]("METRICS")


def test_f1183_denials_are_counted_where_they_happen() -> None:
    auth = _files("authz_abac")["app/auth/authorize.py"]
    assert auth.count("_count_denied(") >= 3  # def + both denial sites
    assert "app.authz.denied" in auth
    assert '"authz_denied": ("app.authz.denied"' not in _files("obs_blog")["app/core/telemetry.py"]  # no double count


def test_f1184_scrub_test_covers_query_keys() -> None:
    test = _files("obs_blog")["tests/test_observability.py"]
    assert '"url.query"' in test and '"http.query"' in test


def test_f1185_nearest_never_returns_a_truncated_scan_as_exact() -> None:
    src = _files("operations_fleet")["app/operations/geo/service.py"]
    calls: list[int] = []

    class Hit:
        def __init__(self, i: int) -> None:
            self.id = i

    async def scan(session: Any, tn: Any, lat: int, lng: int, radius: int, kind: Any) -> Any:
        calls.append(radius)
        if radius > 300:  # dense area: scans above 300 m hit the cap and are arbitrary subsets
            return [(900 - i, Hit(i)) for i in range(5)], True
        return [(10 + i, Hit(100 + i)) for i in range(2)], False

    class PlaceHits:
        def __init__(self, items: list[Any], truncated: bool) -> None:
            self.items, self.truncated = items, truncated

    ns: dict[str, Any] = {
        "_scan": scan,
        "_config": types.SimpleNamespace(MAX_RADIUS_M=5000),
        "_s": types.SimpleNamespace(PlaceHits=PlaceHits),
        "_hit": lambda r, d: (r.id, d),
        "tenant": lambda u: None,
        "_t": types.SimpleNamespace(Any=object),
        "AsyncSession": object,
    }
    ns = _funcs(src, {"places_nearest"}, ns)
    out = asyncio.run(ns["places_nearest"](None, None, (0, 0), 1, None))
    assert out.truncated is False
    assert out.items == [(100, 10)]  # taken from the complete small scan, the true nearest
    assert max(calls) >= 1000 and min(calls) <= 300
