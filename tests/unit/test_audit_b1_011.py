"""Audit B1-011: ledger reserved keys, metrics group cap, keycloak https guard, suite org scope."""

import ast
import importlib.machinery
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures" / "specs"
KC = ROOT.parent / "app" / "core" / "generator" / "features" / "keycloak" / "templates"


def _files(name: str) -> dict[str, str]:
    raw = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return generate(Spec.model_validate(raw))


def _func_src(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(name)


def _register(name: str) -> ModuleType:
    path = str(KC / name)
    loader = importlib.machinery.SourceFileLoader(f"kc_{name.split('.')[0]}", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# --- F-0338 ---


def test_ledger_rejects_reserved_idempotency_prefixes() -> None:
    service = _files("money_ledger")["app/money/ledger/service.py"]
    for fn in ("post_transaction", "reverse_transaction"):
        body = _func_src(service, fn)
        assert "_refuse_reserved_key(body.idempotency_key)" in body.split("_replay_or_conflict")[0], fn  # noqa: E501
        assert "reserved_key" in body, fn


# --- F-0339 ---


def test_generated_metrics_engine_caps_group_cardinality() -> None:
    engine = _files("realtime_metrics")["app/metrics/engine.py"]
    assert "MAX_GROUPS" in engine
    assert "metric_too_many_groups" in engine
    compute = _func_src(engine, "compute")
    assert ".limit(MAX_GROUPS + 1)" in compute
    assert ".limit(MAX_GROUPS + 1)" in _func_src(engine, "_distinct_in_python")


# --- F-0340 ---

EVIL = [
    "http://localhost.evil.com",
    "http://evil.com/?x=localhost",
    "http://127.0.0.1.evil.com",
    "http://evil.com/localhost",
]


@pytest.mark.parametrize("tpl", ["keycloak_register.py.tpl", "keycloak_register_suite.py.tpl"])
@pytest.mark.parametrize("url", EVIL)
def test_register_refuses_http_to_non_local_hosts(
    tpl: str, url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod: Any = _register(tpl)
    doc = tmp_path / "clients.json"
    doc.write_text(json.dumps({"realm": "r"}), encoding="utf-8")
    mod.DOCUMENT = doc
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", url)

    def boom(*a: Any, **k: Any) -> None:
        raise AssertionError("credentials would be sent")

    mod.admin_token = boom
    with pytest.raises(mod.RegisterError):
        mod.main()


@pytest.mark.parametrize("tpl", ["keycloak_register.py.tpl", "keycloak_register_suite.py.tpl"])
@pytest.mark.parametrize("url", ["http://localhost:8080", "http://127.0.0.1:8080", "https://kc.example.com"])
def test_register_allows_local_http_and_https(
    tpl: str, url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod: Any = _register(tpl)
    doc = tmp_path / "clients.json"
    doc.write_text(json.dumps({"realm": "r"}), encoding="utf-8")
    mod.DOCUMENT = doc
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", url)

    class Reached(Exception):
        pass

    def reached(*a: Any, **k: Any) -> None:
        raise Reached

    mod.admin_token = reached
    with pytest.raises(Reached):
        mod.main()


# --- F-0341 ---


def test_suite_register_gives_the_suite_client_the_organization_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod: Any = _register("keycloak_register_suite.py.tpl")
    doc = tmp_path / "clients.json"
    doc.write_text(
        json.dumps(
            {
                "realm": "r",
                "api_client_id": "app",
                "browser_client_ids": [],
                "clients": [{"clientId": "app"}],
                "roles": [],
                "organizations": True,
            }
        ),
        encoding="utf-8",
    )
    mod.DOCUMENT = doc
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "http://localhost:8080")
    seen: list[tuple[str, str]] = []
    mod.admin_token = lambda base: "t"
    mod.ensure_client = lambda admin, token, client: "internal-app"
    mod.ensure_roles = lambda *a, **k: None
    mod.map_scopes = lambda *a, **k: None
    mod.ensure_user_profile = lambda *a, **k: None
    mod.enable_organizations = lambda *a, **k: None
    mod.ensure_default_scope = lambda admin, token, client, scope: seen.append((client, scope))
    assert mod.main() == 0
    assert ("internal-app", "organization") in seen
