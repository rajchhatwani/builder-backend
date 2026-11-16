"""B1-015: generated operations routers refuse NUL in path/query text params with 422 (asyncpg would raise a plain
DBAPIError -> 500). Routers are exec'd with stubbed collaborators and driven through a FastAPI TestClient."""

import json
import sys
import types
from pathlib import Path
from typing import Annotated, Any, Generic, TypeVar
from unittest.mock import MagicMock

import fastapi
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
T = TypeVar("T")


class _Page(BaseModel, Generic[T]):
    items: list[T] = []
    total: int = 0
    limit: int = 0
    offset: int = 0


@pytest.fixture(scope="module")
def files() -> dict[str, str]:
    return generate(Spec.model_validate(json.loads((FIXTURES / "operations_fleet.json").read_text(encoding="utf-8"))))


def _mod(name: str, **attrs: Any) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__path__ = []  # type: ignore[attr-defined]
    m.__dict__.update(attrs)
    return m


def _client(files: dict[str, str], block: str) -> tuple[TestClient, MagicMock]:
    pkg = f"app.operations.{block}"
    svc = MagicMock()
    stubs: dict[str, Any] = {
        "app.auth": _mod("app.auth"),
        "app.auth.models": _mod("app.auth.models", AuthUser=object),
        "app.core": _mod("app.core"),
        "app.core.pagination": _mod("app.core.pagination", Page=_Page),
        "app.db": _mod("app.db", SessionDep=Annotated[Any, fastapi.Depends(lambda: None)]),
        "app.operations": _mod("app.operations"),
        "app.operations.common": _mod("app.operations.common", role_dependency=lambda roles: fastapi.Depends(lambda: None)),
    }
    cfg = _mod(f"{pkg}.config", READ_ROLES=(), WRITE_ROLES=(), ASSIGN_ROLES=(), BOX_CAP=100)
    stubs[pkg] = _mod(pkg)
    stubs[f"{pkg}.config"] = cfg
    stubs[f"{pkg}.service"] = svc
    # schemas: permissive stand-ins (validation under test is the router's own Query/Path rules)
    class _Schemas(types.ModuleType):
        def __getattr__(self, n: str) -> Any:
            if n.startswith("__"):
                raise AttributeError(n)
            if n == "Status":
                return str
            model = type(n, (BaseModel,), {"model_config": {"extra": "allow"}})
            setattr(self, n, model)
            return model

    schemas = _Schemas(f"{pkg}.schemas")
    stubs[f"{pkg}.schemas"] = schemas
    for k in (f"{pkg}.config", f"{pkg}.schemas", f"{pkg}.service"):
        setattr(stubs[pkg], k.rsplit(".", 1)[1], stubs[k])
    saved = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        module = types.ModuleType(f"r_{block}")
        sys.modules[module.__name__] = module  # pydantic generics (Page[...]) look the module up
        exec(compile(files[f"{pkg.replace('.', '/')}/router.py"], "router.py", "exec"), module.__dict__)  # noqa: S102
    finally:
        sys.modules.pop(f"r_{block}", None)
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old
    app = fastapi.FastAPI()
    app.include_router(module.router)
    return TestClient(app, raise_server_exceptions=False), svc


def test_location_nul_path_and_query_are_422(files: dict[str, str]) -> None:
    c, svc = _client(files, "location")
    assert c.get("/location/positions/a%00b").status_code == 422
    assert c.get("/location/positions/a%00b/history").status_code == 422
    box = {"min_lat_micro": 1, "min_lng_micro": 1, "max_lat_micro": 2, "max_lng_micro": 2}
    assert c.get("/location/positions", params={**box, "subject_kind": "k\x00"}).status_code == 422
    assert not svc.latest.called and not svc.history.called and not svc.in_box.called


def test_matching_nul_query_is_422(files: dict[str, str]) -> None:
    c, svc = _client(files, "matching")
    assert c.get("/matching/assignments", params={"request_ref": "\x00"}).status_code == 422
    assert c.get("/matching/assignments", params={"candidate_id": "a\x00"}).status_code == 422
    assert not svc.list_assignments.called


def test_prediction_nul_query_is_422(files: dict[str, str]) -> None:
    c, svc = _client(files, "prediction")
    for p in ({"subject_ref": "\x00"}, {"kind": "k\x00"}):
        assert c.get("/prediction/records", params=p).status_code == 422
    for p in ({"kind": "k\x00"}, {"model_id": "m\x00"}):
        assert c.get("/prediction/stats", params=p).status_code == 422
    assert not svc.list_records.called and not svc.stats.called
