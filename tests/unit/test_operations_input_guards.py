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


def test_matching_ignores_stale_positions(files: dict[str, str]) -> None:
    src = files["app/operations/matching/service.py"]
    assert "stale_position" in src and "POSITION_MAX_AGE_SECONDS" in src
    assert "POSITION_MAX_AGE_SECONDS" in files["app/operations/matching/config.py"]
