"""Audit B1-054 regressions: AI pack + api_edge generated code (F-0306..F-0313)."""

import ast
import asyncio
import copy
import json
import time
import types
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _raw(name: str = "ai_documents_knowledge") -> dict[str, Any]:
    return copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def _files(raw: dict[str, Any]) -> dict[str, str]:
    return generate(Spec.model_validate(raw))


def _module(source: str) -> types.ModuleType:
    mod = types.ModuleType("m")
    exec(compile(source, "m", "exec"), mod.__dict__)  # noqa: S102
    return mod


def test_f0306_ai_fingerprints_use_the_key_every_algorithm_has() -> None:
    raw = _raw()
    raw["auth"]["jwt_algorithm"] = "RS256"
    files = _files(raw)
    for name, source in files.items():
        if name.startswith("app/ai/"):
            assert "auth_jwt_secret" not in source, name
    assert "get_auth_settings().jwt_key" in files["app/ai/service.py"]
    assert "def jwt_key" in files["app/auth/config.py"]


def test_f0306_keycloak_with_ai_is_rejected() -> None:
    raw = _raw()
    raw["auth"]["provider"] = "keycloak"
    assert "needs_builtin_auth" in {i.code for i in validate(Spec.model_validate(raw))}


def test_f0307_fake_extract_is_linear() -> None:
    providers = _module(_files(_raw())["app/ai/providers.py"])
    contents = ["EXTRACT FIELDS: " + ",".join(["a"] * 2000), "SEGMENT 0\na: x" + " " * 19000 + "y"]
    started = time.monotonic()
    result = asyncio.run(providers.complete("fake", "fake-small", contents, 100_000, True, False, False))
    assert time.monotonic() - started < 2
    assert result.text.startswith('{"fields":{"a":')


def test_f0308_anonymous_callers_are_not_charged_quota() -> None:
    files = _files(_raw("api_edge_orders"))
    guard = files["app/api_edge/guard.py"]
    quota_fn = guard[guard.index("async def _quota") : guard.index("async def guard")]
    assert quota_fn.index("who.authenticated") < quota_fn.index("quota.charge")


def test_f0309_f0310_auth_and_ai_routes_are_never_captured() -> None:
    files = _files(_raw("api_edge_orders"))
    source = files["app/api_edge/idempotency.py"]
    tree = ast.parse(source)
    wanted = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name == "capturable") or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "NO_CAPTURE_PREFIXES")]
    mod = types.ModuleType("p")
    exec(compile(ast.Module(body=wanted, type_ignores=[]), "p", "exec"), mod.__dict__)  # noqa: S102
    assert not mod.capturable("/auth/login") and not mod.capturable("/auth/refresh")
    assert not mod.capturable("/ai/complete") and not mod.capturable("/ai")
    assert mod.capturable("/orders") and mod.capturable("/authors")
    assert "idempotency.capturable(path)" in files["app/api_edge/middleware.py"]


def test_f0311_empty_read_roles_do_not_show_every_document() -> None:
    source = _files(_raw())["app/ai/documents_service.py"]
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_sees_all")
    mod = types.ModuleType("d")
    cfg = types.SimpleNamespace(READ_ROLES=(), REVIEW_ROLES=("admin",))
    gateway = types.SimpleNamespace(has_role=lambda user, roles: not roles or bool(set(user.roles) & set(roles)))
    mod.__dict__.update(_config=cfg, _gateway=gateway, _t=__import__("typing"))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "d", "exec"), mod.__dict__)  # noqa: S102
    assert mod._sees_all(types.SimpleNamespace(roles=["customer"])) is False
    assert mod._sees_all(types.SimpleNamespace(roles=["admin"])) is True
    cfg.REVIEW_ROLES = ()
    assert mod._sees_all(types.SimpleNamespace(roles=["admin"])) is False


def test_f0312_stale_reservations_are_released_before_the_replay_lookup() -> None:
    source = _files(_raw())["app/ai/service.py"]
    body = source[source.index("async def complete(") :]
    assert body.index("_release_stale(") < body.index("AiCall.idempotency_key == body.idempotency_key")
    assert body.count("await _release_stale(") == 1


def test_f0313_nul_characters_are_refused_by_the_schemas() -> None:
    files = _files(_raw())
    pydantic = pytest.importorskip("pydantic")
    gw = _module(files["app/ai/schemas.py"])
    docs = _module(files["app/ai/documents_schemas.py"])
    kn = _module(files["app/ai/knowledge_schemas.py"])
    with pytest.raises(pydantic.ValidationError):
        gw.CompleteIn(stage="s", messages=[{"role": "user", "content": "a\x00b"}])
    with pytest.raises(pydantic.ValidationError):
        docs.DocumentIn(kind="invoice", title="t", content="a\x00b")
    with pytest.raises(pydantic.ValidationError):
        docs.CorrectIn(value="a\x00b")
    with pytest.raises(pydantic.ValidationError):
        kn.SourceIn(title="t", text="a\x00b")
    with pytest.raises(pydantic.ValidationError):
        kn.AskIn(question="a\x00b")
    assert docs.DocumentIn(kind="invoice", title="t", content="ok").content == "ok"
