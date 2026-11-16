"""B1-014: generated operations schemas refuse "/" in subject ids and NUL in text (422, not 500); the subject cap is
serialised; matching ignores stale stored positions."""

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


@pytest.fixture(scope="module")
def files() -> dict[str, str]:
    return generate(Spec.model_validate(json.loads((FIXTURES / "operations_fleet.json").read_text(encoding="utf-8"))))


def _load(files: dict[str, str], name: str, path: str, stubs: dict[str, Any]) -> types.ModuleType:
    saved = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        module = types.ModuleType(name)
        exec(compile(files[path], path, "exec"), module.__dict__)  # noqa: S102
        return module
    finally:
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old


def _pkg(name: str, path: str, files: dict[str, str]) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []  # type: ignore[attr-defined]
    exec(compile(files[path], path, "exec"), module.__dict__)  # noqa: S102
    return module


def _points(files: dict[str, str]) -> dict[str, Any]:
    errors = types.ModuleType("app.core.errors")
    errors.AppError = Exception  # type: ignore[attr-defined]
    stubs: dict[str, Any] = {"app.core.errors": errors}
    for n in ("app.operations", "app.operations.matching", "app.operations.prediction"):
        m = types.ModuleType(n)
        m.__path__ = []  # type: ignore[attr-defined]
        stubs[n] = m
    saved = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        gm = types.ModuleType("app.operations.geomath")
        exec(compile(files["app/operations/geomath.py"], "g.py", "exec"), gm.__dict__)  # noqa: S102
        sys.modules["app.operations.geomath"] = gm
        pts = types.ModuleType("app.operations.points")
        exec(compile(files["app/operations/points.py"], "points.py", "exec"), pts.__dict__)  # noqa: S102
        cfg_m = types.ModuleType("app.operations.matching.config")
        exec(compile(files["app/operations/matching/config.py"], "c.py", "exec"), cfg_m.__dict__)  # noqa: S102
        cfg_p = types.ModuleType("app.operations.prediction.config")
        exec(compile(files["app/operations/prediction/config.py"], "c.py", "exec"), cfg_p.__dict__)  # noqa: S102
    finally:
        sys.modules.pop("app.operations.geomath", None)
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old
    return {"app.operations.points": pts, "app.operations.matching.config": cfg_m, "app.operations.prediction.config": cfg_p, **stubs}


def _schemas(files: dict[str, str], block: str) -> Any:
    stubs = _points(files)
    for n in ("app.operations.matching", "app.operations.prediction"):
        setattr(stubs[n], "config", stubs[f"{n}.config"])
    return _load(files, f"s_{block}", f"app/operations/{block}/schemas.py", stubs)


_POINT = {"lat_micro": 1_000_000, "lng_micro": 2_000_000}


def test_location_subject_id_refuses_slash_and_nul(files: dict[str, str]) -> None:
    s = _schemas(files, "location")
    assert s.PositionIn(subject_id="driver-42", seq=1, **_POINT).subject_id == "driver-42"
    for bad in ("driver/42", "/", "a\x00b"):
        with pytest.raises(ValidationError):
            s.PositionIn(subject_id=bad, seq=1, **_POINT)
    with pytest.raises(ValidationError):
        s.PositionIn(subject_id="ok", subject_kind="a\x00", seq=1, **_POINT)


def test_matching_ids_refuse_nul(files: dict[str, str]) -> None:
    s = _schemas(files, "matching")
    assert s.CandidateIn(id="D1", **_POINT).id == "D1"
    with pytest.raises(ValidationError):
        s.CandidateIn(id="D\x001", **_POINT)
    with pytest.raises(ValidationError):
        s.AssignIn(request_ref="r\x00", candidates=[{"id": "D1", **_POINT}], **{"lat_micro": 1, "lng_micro": 2})
    with pytest.raises(ValidationError):
        s.BatchRequest(request_ref="r\x00", point={"lat_micro": 1, "lng_micro": 2})


def test_prediction_refuses_nul(files: dict[str, str]) -> None:
    s = _schemas(files, "prediction")
    assert s.PredictIn(kind="k", subject_ref="x", features={"a": "ok"})
    for kw in ({"subject_ref": "x\x00"}, {"features": {"a": "\x00"}}, {"features": {"a\x00": 1}}):
        with pytest.raises(ValidationError):
            s.PredictIn(**{"kind": "k", "subject_ref": "x", **kw})


def test_location_new_subjects_are_serialised_by_an_advisory_lock(files: dict[str, str]) -> None:
    src = files["app/operations/location/service.py"]
    lock, count = src.index("pg_advisory_xact_lock"), src.index("_sa.func.count()")
    assert lock < count


def _service(files: dict[str, str]) -> Any:
    from datetime import UTC, datetime, timedelta  # noqa: F401
    from unittest.mock import MagicMock

    stubs = _points(files)
    geo = types.ModuleType("app.operations.geomath")
    exec(compile(files["app/operations/geomath.py"], "g.py", "exec"), geo.__dict__)  # noqa: S102
    for n in ("app.operations.matching",):
        setattr(stubs[n], "config", stubs[f"{n}.config"])
    stubs["app.operations.geomath"] = geo
    sc = _load(files, "sc", "app/operations/matching/scoring.py", stubs)
    stubs["app.operations.matching.scoring"] = sc
    setattr(stubs["app.operations.matching"], "scoring", sc)
    stubs["app.operations.matching.schemas"] = _load(files, "ms", "app/operations/matching/schemas.py", stubs)
    for n in ("app.operations.common", "app.operations.location.models", "app.operations.matching.models",
              "app.operations.location"):
        stubs[n] = MagicMock()
    stubs["app.core.errors"].AppError = type("AppError", (Exception,), {
        "__init__": lambda self, code, msg, status=400, details=None: setattr(self, "code", code) or None})
    return _load(files, "svc", "app/operations/matching/service.py", stubs)


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def scalars(self) -> list[Any]:
        return self.rows


class _Session:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    async def execute(self, _stmt: Any) -> _Rows:
        return _Rows(self.rows)


@pytest.mark.asyncio
async def test_stale_position_excludes_only_that_candidate(files: dict[str, str]) -> None:
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace as NS

    svc = _service(files)
    svc._sa = NS(select=lambda *_a: NS(where=lambda *_b: None))
    svc.scoped = lambda stmt, *_a: stmt
    now = datetime.now(UTC)
    old = now - timedelta(seconds=svc._config.POSITION_MAX_AGE_SECONDS + 60)
    rows = [NS(subject_id="old", updated_at=old, lat_micro=1, lng_micro=2),
            NS(subject_id="fresh", updated_at=now, lat_micro=3, lng_micro=4)]
    given = [svc._s.CandidateIn(id=i) for i in ("old", "fresh")] + [svc._s.CandidateIn(id="own", **_POINT)]
    cands, excluded = await svc._candidates(_Session(rows), None, given)
    assert [c.id for c in cands] == ["fresh", "own"]
    assert excluded == [("old", "stale_position")]

    class _Body:
        candidates = given
        point = svc._s.RankIn.model_fields and NS(micro=(3, 4))

    out = await svc.rank(_Session(rows), NS(id=None), _Body)
    assert {e.candidate_id: e.reason for e in out.excluded}["old"] == "stale_position"
    assert "fresh" in {i.candidate_id for i in out.items}
