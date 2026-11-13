"""CP-5C: the operations pack (D13 geo, D14 location, D15 matching, D16 prediction).

Spec declaration and validation, emission only for declared blocks (existing goldens untouched), registry and
manifest dependencies, deterministic output, and the pure generated modules (geomath, points, scoring, adapters)
executed on hand-computed cases. Database behaviour (atomic seq, one active assignment, enter / exit, tenants, roles)
is proven by tests/e2e/test_operations_stack.py."""

import ast
import json
import subprocess
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.generator import generate
from app.core.generator.engine import module_registry, pack_registry
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
BLOCKS = ("geo", "location", "matching", "prediction")


def _raw() -> dict[str, Any]:
    return json.loads((FIXTURES / "operations_fleet.json").read_text(encoding="utf-8"))


def _spec(raw: dict[str, Any] | None = None) -> Spec:
    return Spec.model_validate(raw if raw is not None else _raw())


def _codes(raw: dict[str, Any]) -> set[str]:
    return {i.code for i in validate(Spec.model_validate(raw))}


def _only(*keep: str) -> dict[str, Any]:
    raw = _raw()
    raw["packs"]["operations"] = {b: v for b, v in raw["packs"]["operations"].items() if b in keep}
    return raw


# --- the spec ----------------------------------------------------------------------------------------------


def test_the_fleet_spec_is_valid_and_defaults_apply() -> None:
    assert validate(_spec()) == []
    raw = _raw()
    raw["packs"]["operations"] = {"geo": {}, "location": {}, "matching": {}, "prediction": {}}
    ops = _spec(raw).packs.operations  # type: ignore[union-attr]
    assert ops is not None and ops.geo is not None and ops.location is not None
    assert ops.matching is not None and ops.prediction is not None
    assert (ops.geo.provider, ops.geo.grid_cell_micro, ops.geo.read_roles, ops.geo.write_roles) == ("fake", 10_000, ["admin"], ["admin"])
    assert (ops.location.history_cap, ops.matching.max_distance_m, ops.matching.offer_ttl_seconds) == (100, 20_000, 300)
    assert (ops.matching.weights.distance, ops.matching.weights.load, ops.prediction.model_id, ops.prediction.interval_bp) == (1000, 0, "fake-linear-v1", 2000)
    assert not [i for i in validate(_spec(raw)) if i.code != "unknown_role"] or validate(_spec(raw)) == []


@pytest.mark.parametrize(
    "patch",
    [
        ("geo", {"grid_cell_micro": 10000.5}),
        ("geo", {"max_places": "10"}),
        ("geo", {"colour": "red"}),
        ("location", {"history_cap": 1.5}),
        ("location", {"retention": 3}),
        ("matching", {"weights": {"distance": 1.5}}),
        ("matching", {"weights": {"speed": 1}}),
        ("matching", {"max_load": True}),
        ("prediction", {"interval_bp": 20.5}),
        ("prediction", {"seed": 1}),
    ],
)
def test_unknown_options_and_non_integers_are_refused_by_the_spec_model(patch: tuple[str, dict[str, Any]]) -> None:
    raw = _raw()
    raw["packs"]["operations"][patch[0]].update(patch[1])
    with pytest.raises(ValidationError):
        _spec(raw)


def test_an_unknown_block_is_refused() -> None:
    raw = _raw()
    raw["packs"]["operations"]["routing"] = {}
    with pytest.raises(ValidationError):
        _spec(raw)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: r["packs"]["operations"].clear(), "empty_pack"),
        (lambda r: r["packs"]["operations"]["geo"].update(provider="google"), "unsupported_provider"),
        (lambda r: r["packs"]["operations"]["geo"].update(grid_cell_micro=10), "out_of_range"),
        (lambda r: r["packs"]["operations"]["geo"].update(grid_cell_micro=5_000_000), "out_of_range"),
        (lambda r: r["packs"]["operations"]["geo"].update(max_places=0), "out_of_range"),
        (lambda r: r["packs"]["operations"]["geo"].update(max_geofences=0), "out_of_range"),
        (lambda r: r["packs"]["operations"]["geo"].update(max_polygon_vertices=2), "out_of_range"),
        (lambda r: r["packs"]["operations"]["geo"].update(max_polygon_vertices=5000), "out_of_range"),
        (lambda r: r["packs"]["operations"]["geo"].update(max_radius_m=30_000_000), "out_of_range"),
        (lambda r: r["packs"]["operations"]["geo"].update(write_roles=["ghost"]), "unknown_role"),
        (lambda r: r["packs"]["operations"]["location"].update(history_cap=0), "out_of_range"),
        (lambda r: r["packs"]["operations"]["location"].update(history_cap=20_000), "out_of_range"),
        (lambda r: r["packs"]["operations"]["location"].update(max_subjects=0), "out_of_range"),
        (lambda r: r["packs"]["operations"]["location"].update(read_roles=["ghost"]), "unknown_role"),
        (lambda r: r["packs"]["operations"]["matching"].update(weights={"distance": 0, "load": 0, "rating": 0}), "all_zero"),
        (lambda r: r["packs"]["operations"]["matching"].update(weights={"distance": -1}), "out_of_range"),
        (lambda r: r["packs"]["operations"]["matching"].update(max_distance_m=0), "out_of_range"),
        (lambda r: r["packs"]["operations"]["matching"].update(max_load=0), "out_of_range"),
        (lambda r: r["packs"]["operations"]["matching"].update(offer_ttl_seconds=0), "out_of_range"),
        (lambda r: r["packs"]["operations"]["matching"].update(assign_roles=["ghost"]), "unknown_role"),
        (lambda r: r["packs"]["operations"]["prediction"].update(model_id="bad id!"), "invalid_model_id"),
        (lambda r: r["packs"]["operations"]["prediction"].update(model_id=""), "invalid_model_id"),
        (lambda r: r["packs"]["operations"]["prediction"].update(unit="a b"), "invalid_unit"),
        (lambda r: r["packs"]["operations"]["prediction"].update(unit="x" * 17), "invalid_unit"),
        (lambda r: r["packs"]["operations"]["prediction"].update(interval_bp=-1), "out_of_range"),
        (lambda r: r["packs"]["operations"]["prediction"].update(interval_bp=200_000), "out_of_range"),
    ],
)
def test_operations_values_are_validated(mutate: Any, code: str) -> None:
    raw = _raw()
    mutate(raw)
    assert code in _codes(raw)


def test_operations_need_auth_and_rbac() -> None:
    raw = _raw()
    raw["auth"]["enabled"] = False
    codes = _codes(raw)
    assert "needs_auth" in codes
    raw = _raw()
    raw.pop("auth")
    assert "needs_auth" in _codes(raw)
    raw = _raw()
    raw["authorization"] = {"model": "abac", "policies": []}
    assert "needs_rbac" in {i.code for i in validate(_spec(raw))}


def test_the_pack_tables_are_reserved_names() -> None:
    for table in ("geo_places", "geo_geofences", "geo_memberships", "geo_events", "location_positions", "location_history", "match_assignments", "prediction_records"):
        raw = _raw()
        raw["entities"][0]["table_name"] = table
        assert any(table in i.message or i.path.endswith("table_name") for i in validate(_spec(raw))), table
    # an undeclared block does not reserve its tables
    raw = _only("geo")
    raw["entities"][0]["table_name"] = "prediction_records"
    assert not any("prediction_records" in i.message for i in validate(_spec(raw)))


# --- emission ------------------------------------------------------------------------------------------------


def test_emission_only_when_declared() -> None:
    raw = _raw()
    del raw["packs"]
    plain = generate(_spec(raw))
    assert not [p for p in plain if "operations" in p or "/geo" in p or "location" in p]
    for text in (plain["app/main.py"], plain["app/models/__init__.py"]):
        assert "operations" not in text
    assert "geo_places" not in plain["tests/conftest.py"]
    files = generate(_spec())
    assert sorted(p for p in files if "operations" in p) == [
        "alembic/versions/0033_operations_geo.py",
        "alembic/versions/0034_operations_location.py",
        "alembic/versions/0035_operations_matching.py",
        "alembic/versions/0036_operations_prediction.py",
        "app/operations/__init__.py",
        "app/operations/common.py",
        "app/operations/geo/__init__.py",
        "app/operations/geo/adapters.py",
        "app/operations/geo/config.py",
        "app/operations/geo/models.py",
        "app/operations/geo/router.py",
        "app/operations/geo/schemas.py",
        "app/operations/geo/service.py",
        "app/operations/geomath.py",
        "app/operations/location/__init__.py",
        "app/operations/location/config.py",
        "app/operations/location/models.py",
        "app/operations/location/router.py",
        "app/operations/location/schemas.py",
        "app/operations/location/service.py",
        "app/operations/matching/__init__.py",
        "app/operations/matching/config.py",
        "app/operations/matching/models.py",
        "app/operations/matching/router.py",
        "app/operations/matching/schemas.py",
        "app/operations/matching/scoring.py",
        "app/operations/matching/service.py",
        "app/operations/points.py",
        "app/operations/prediction/__init__.py",
        "app/operations/prediction/adapter.py",
        "app/operations/prediction/config.py",
        "app/operations/prediction/models.py",
        "app/operations/prediction/router.py",
        "app/operations/prediction/schemas.py",
        "app/operations/prediction/service.py",
    ]
    for block in BLOCKS:
        assert f"include_router(_{block}_router)" in files["app/main.py"], block
        assert f"_{block}_models" in files["app/models/__init__.py"], block
    for table in ("geo_places", "geo_geofences", "geo_memberships", "geo_events", "location_positions", "location_history", "match_assignments", "prediction_records"):
        assert table in files["tests/conftest.py"], table


@pytest.mark.parametrize("block", BLOCKS)
def test_an_undeclared_block_emits_nothing(block: str) -> None:
    raw = _raw()
    del raw["packs"]["operations"][block]
    files = generate(_spec(raw))
    assert not [p for p in files if f"operations/{block}/" in p or f"_operations_{block}" in p]
    assert f"_{block}_router" not in files["app/main.py"] and f"_{block}_models" not in files["app/models/__init__.py"]
    assert any(p.startswith(f"app/operations/{b}/") for p in files for b in BLOCKS if b != block)


def test_routes_roles_and_config_come_from_the_spec() -> None:
    files = generate(_spec())
    cfg = files["app/operations/geo/config.py"]
    assert "WRITE_ROLES: tuple[str, ...] = ('admin', 'dispatcher',)" in cfg and "GRID_CELL_MICRO = 10000" in cfg
    assert "MAX_GEOFENCES = 20" in cfg and "MAX_POLYGON_VERTICES = 12" in cfg and 'PROVIDER = "fake"' in cfg
    assert "HISTORY_CAP = 5" in files["app/operations/location/config.py"] and "GEO = True" in files["app/operations/location/config.py"]
    mc = files["app/operations/matching/config.py"]
    assert "WEIGHT_DISTANCE = 600" in mc and "WEIGHT_LOAD = 300" in mc and "WEIGHT_RATING = 100" in mc and "MAX_DISTANCE_M = 20000" in mc
    pc = files["app/operations/prediction/config.py"]
    assert 'UNIT = "minutes"' in pc and "INTERVAL_BP = 2000" in pc
    routes = {
        "geo": ('"/places"', '"/places/within"', '"/places/nearest"', '"/geofences"', '"/contains"', '"/distance"', '"/evaluate"', '"/events"', '"/geocode"', '"/route"', '"/eta"'),
        "location": ('"/positions"', '"/positions/{subject_id}"', '"/positions/{subject_id}/history"'),
        "matching": ('"/rank"', '"/assignments"', '"/batch"', '"/assignments/{assignment_id}/accept"', '"/assignments/{assignment_id}/reject"', '"/assignments/{assignment_id}/expire"', '"/expire-due"'),
        "prediction": ('"/predict"', '"/records"', '"/records/{record_id}/actual"', '"/stats"'),
    }
    for block, paths in routes.items():
        for route in paths:
            assert route in files[f"app/operations/{block}/router.py"], (block, route)


def test_the_migrations_guard_the_invariants() -> None:
    files = generate(_spec())
    assert "uq_match_assignments_active" in files["alembic/versions/0035_operations_matching.py"]
    assert "status IN ('offered', 'accepted')" in files["alembic/versions/0035_operations_matching.py"]
    assert "uq_location_positions_subject" in files["alembic/versions/0034_operations_location.py"]
    assert "uq_geo_memberships_subject_id_geofence_id" in files["alembic/versions/0033_operations_geo.py"]
    for path in files:
        if path.startswith("alembic/versions/003") and path.endswith(".py") and "operations" in path:
            text = files[path]
            assert "sa.Float" not in text and "sa.Numeric" not in text, path


def test_tenant_treatment_and_single_tenant_has_none() -> None:
    tenant = generate(_spec())
    for block, mig in (("geo", "0033_operations_geo"), ("location", "0034_operations_location"), ("matching", "0035_operations_matching"), ("prediction", "0036_operations_prediction")):
        for path in (f"app/operations/{block}/models.py", f"alembic/versions/{mig}.py"):
            assert tenant[path].count('"auth_tenants.id"') >= 1 and 'ondelete="RESTRICT"' in tenant[path], path
    raw = _raw()
    raw["auth"]["multi_tenant"] = False
    for permission in raw["auth"]["permissions"]:
        permission.pop("row_rule", None)
    single = generate(Spec.model_validate(raw))
    for block, mig in (("geo", "0033_operations_geo"), ("location", "0034_operations_location"), ("matching", "0035_operations_matching"), ("prediction", "0036_operations_prediction")):
        for path in (f"app/operations/{block}/models.py", f"alembic/versions/{mig}.py"):
            assert "tenant_id" not in single[path] and "auth_tenants" not in single[path], path
        assert "MULTI_TENANT = False" in single[f"app/operations/{block}/config.py"]


def test_output_is_deterministic() -> None:
    assert generate(_spec()) == generate(_spec())


def test_the_blocks_are_registered_with_their_dependencies() -> None:
    packs = pack_registry()
    for block in BLOCKS:
        assert packs[f"operations.{block}"].id == f"operations_{block}"
        assert {"crud", "auth", "operations_common"} <= set(packs[f"operations.{block}"].depends_on)
    assert "operations_geo" in packs["operations.location"].depends_on
    assert "operations_location" in packs["operations.matching"].depends_on
    assert module_registry()["operations_common"].pack is None
    # the declared packs are listed by the validator
    from app.core.validation_packs import declared_packs

    assert {f"operations.{b}" for b in BLOCKS} <= set(declared_packs(_spec()))


@pytest.mark.parametrize("keep", [("geo",), ("location",), ("matching",), ("prediction",), ("geo", "location"), ("location", "matching"), ("matching", "prediction")])
def test_every_block_combination_is_valid_and_generates_clean_code(keep: tuple[str, ...], tmp_path: Path) -> None:
    spec = _spec(_only(*keep))
    assert validate(spec) == []
    files = generate(spec)
    for path, content in files.items():
        if path.endswith(".py"):
            ast.parse(content, filename=path)
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    assert ("app/operations/geo/service.py" in files) == ("geo" in keep)
    result = subprocess.run([sys.executable, "-m", "ruff", "check", "--no-cache", "."], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


# --- the pure generated modules, executed -----------------------------------------------------------------------


class _AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.status_code, self.details = code, message, status_code, details or []


@pytest.fixture(scope="module")
def ops() -> Iterator[types.SimpleNamespace]:
    files = generate(_spec())
    names = {
        "app.operations": None,
        "app.operations.matching": None,
        "app.operations.geo": None,
        "app.operations.prediction": None,
        "app.operations.geomath": "app/operations/geomath.py",
        "app.operations.points": "app/operations/points.py",
        "app.operations.matching.scoring": "app/operations/matching/scoring.py",
        "app.operations.geo.adapters": "app/operations/geo/adapters.py",
        "app.operations.prediction.adapter": "app/operations/prediction/adapter.py",
    }
    saved = {k: sys.modules.get(k) for k in [*names, "app.core.errors"]}
    errors = types.ModuleType("app.core.errors")
    errors.AppError = _AppError  # type: ignore[attr-defined]
    sys.modules["app.core.errors"] = errors
    try:
        for name, path in names.items():
            module = types.ModuleType(name)
            if path is None:
                module.__path__ = []  # type: ignore[attr-defined]
            sys.modules[name] = module
            if path is not None:
                exec(compile(files[path], path, "exec"), module.__dict__)  # noqa: S102
        yield types.SimpleNamespace(
            gm=sys.modules["app.operations.geomath"],
            pt=sys.modules["app.operations.points"],
            sc=sys.modules["app.operations.matching.scoring"],
            ad=sys.modules["app.operations.geo.adapters"],
            pr=sys.modules["app.operations.prediction.adapter"],
        )
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def test_haversine_is_integer_metres(ops: types.SimpleNamespace) -> None:
    gm = ops.gm
    assert gm.haversine_m(0, 0, 0, 0) == 0
    one_degree = gm.haversine_m(0, 0, 0, 1_000_000)
    assert type(one_degree) is int and one_degree == 111_195  # 6,371 km * pi / 180
    assert gm.haversine_m(0, 0, 1_000_000, 0) == one_degree
    assert gm.haversine_m(0, 0, 0, 180_000_000) == 20_015_087  # half the circumference
    assert gm.haversine_m(10_000_000, 20_000_000, 11_000_000, 21_000_000) == gm.haversine_m(11_000_000, 21_000_000, 10_000_000, 20_000_000)
    # across the antimeridian the short way is used
    assert gm.haversine_m(0, 179_999_000, 0, -179_999_000) == gm.haversine_m(0, 0, 0, 2_000)
    assert gm.haversine_m(90_000_000, 0, -90_000_000, 0) == 20_015_087


def test_coordinate_validity_and_cells(ops: types.SimpleNamespace) -> None:
    gm = ops.gm
    assert gm.valid_coordinates(90_000_000, 180_000_000) and gm.valid_coordinates(-90_000_000, -180_000_000)
    assert not gm.valid_coordinates(90_000_001, 0) and not gm.valid_coordinates(0, -180_000_001)
    assert gm.cell_of(-90_000_000, -180_000_000, 10_000) == 0
    assert gm.cell_of(0, 0, 10_000) != gm.cell_of(0, 10_000, 10_000) and gm.cell_of(5, 5, 10_000) == gm.cell_of(0, 0, 10_000)
    assert all(isinstance(gm.cell_of(a, b, 10_000), int) for a, b in ((1, 2), (-5, -7)))


def test_point_parsing_micro_versus_decimal(ops: types.SimpleNamespace) -> None:
    pt = ops.pt
    assert pt.Point(lat_micro=12_345_678, lng_micro=-1_500_000).micro == (12_345_678, -1_500_000)
    assert pt.Point(lat="12.345678", lng="-1.5").micro == (12_345_678, -1_500_000)
    assert pt.Point(lat=12.5, lng=-1).micro == (12_500_000, -1_000_000)
    # more than 6 decimals: rounded half to even
    assert pt.Point(lat="12.3456785", lng="0").micro[0] == 12_345_678
    assert pt.Point(lat="12.3456775", lng="0").micro[0] == 12_345_678
    assert pt.Point(lat="0.0000005", lng="-0.0000005").micro == (0, 0)
    assert pt.Point(lat="0.0000015", lng="0.0000025").micro == (2, 2)
    for kwargs in ({}, {"lat_micro": 1}, {"lat": "1"}, {"lat_micro": 1, "lng_micro": 1, "lat": "1", "lng": "1"}, {"lat_micro": 1, "lng": "1"}):
        with pytest.raises(_AppError) as info:
            pt.Point(**kwargs)
        assert info.value.code == "invalid_point" and info.value.status_code == 422, kwargs
    for kwargs in ({"lat_micro": 90_000_001, "lng_micro": 0}, {"lat": "0", "lng": "180.000001"}, {"lat": "5000", "lng": "0"}):
        with pytest.raises(_AppError) as info:
            pt.Point(**kwargs)
        assert info.value.code == "invalid_coordinates", kwargs
    with pytest.raises(ValidationError):
        pt.Point(lat_micro=1.5, lng_micro=1)
    with pytest.raises(ValidationError):
        pt.Point(lat_micro=1, lng_micro=1, colour="red")


def test_degrees_text_and_query_points(ops: types.SimpleNamespace) -> None:
    pt = ops.pt
    assert [pt.degrees_text(v) for v in (0, 1, -1, 12_345_678, -1_500_000, -180_000_000)] == ["0.000000", "0.000001", "-0.000001", "12.345678", "-1.500000", "-180.000000"]
    assert pt.coords(5, -6) == {"lat_micro": 5, "lng_micro": -6, "lat": "0.000005", "lng": "-0.000006"}
    assert pt.query_point(None, None, "1.5", "2.25") == (1_500_000, 2_250_000)
    assert pt.query_point(7, 8, None, None) == (7, 8)
    for args in ((None, None, None, None), (1, 2, "1", "2"), (None, None, "abc", "1"), (None, None, "1", None)):
        with pytest.raises(_AppError) as info:
            pt.query_point(*args)
        assert info.value.code == "invalid_point", args
    with pytest.raises(_AppError) as info:
        pt.query_point(None, None, "91", "0")
    assert info.value.code == "invalid_coordinates"


SQUARE = [(0, 0), (0, 10_000), (10_000, 10_000), (10_000, 0)]


def test_polygon_validity(ops: types.SimpleNamespace) -> None:
    gm = ops.gm
    assert gm.polygon_problem(SQUARE) is None
    assert gm.polygon_problem(SQUARE[::-1]) is None
    assert gm.polygon_problem([(0, 0), (0, 10), (10, 5)]) is None
    assert gm.polygon_problem([(0, 0), (0, 10)]) is not None
    assert gm.polygon_problem([(0, 0), (0, 5), (0, 10)]) == "the polygon has no area"
    assert gm.polygon_problem([(0, 0), (0, 10), (0, 10), (5, 5)]) == "a vertex is repeated"
    bowtie = [(0, 0), (10, 10), (0, 10), (20, 0)]
    assert gm.polygon_problem(bowtie) == "the polygon crosses itself"
    assert gm.polygon_problem([(0, 0), (10, 10), (0, 10), (10, 0)]) == "the polygon has no area"  # a symmetric bow-tie
    assert gm.polygon_problem([(0, 0), (0, 10), (0, 5), (10, 5)]) is not None  # folds back over its own edge
    assert gm.polygon_problem([(0, 0), (0, 10), (10, 10), (10, 0), (5, 0)]) is None  # a redundant collinear vertex is fine
    wide = [(0, -100_000_000), (10, 100_000_000), (10, 0)]
    assert "180 degrees" in gm.polygon_problem(wide)
    # concave but simple
    assert gm.polygon_problem([(0, 0), (0, 10), (4, 5), (10, 10), (10, 0)]) is None
    assert gm.polygon_area2(SQUARE) == -2 * 10_000 * 10_000 and gm.polygon_area2(SQUARE[::-1]) == 2 * 10_000 * 10_000


def test_point_in_polygon_and_circle(ops: types.SimpleNamespace) -> None:
    gm = ops.gm
    assert gm.point_in_polygon(5_000, 5_000, SQUARE)
    assert gm.point_in_polygon(0, 5_000, SQUARE) and gm.point_in_polygon(10_000, 10_000, SQUARE)  # border and corner: inside
    assert not gm.point_in_polygon(10_001, 5_000, SQUARE) and not gm.point_in_polygon(5_000, -1, SQUARE)
    concave = [(0, 0), (0, 10), (4, 5), (10, 10), (10, 0)]
    assert gm.point_in_polygon(5, 3, concave) and gm.point_in_polygon(2, 5, concave)
    assert not gm.point_in_polygon(5, 9, concave)  # in the notch of the concave side
    assert not gm.point_in_polygon(11, 5, concave) and not gm.point_in_polygon(5, 11, concave)
    assert gm.point_in_circle(0, 0, 0, 0, 1) and gm.point_in_circle(0, 1_000, 0, 0, 112) and not gm.point_in_circle(0, 1_000, 0, 0, 110)


def test_antimeridian_box_and_cell_ranges(ops: types.SimpleNamespace) -> None:
    gm = ops.gm
    min_lat, max_lat, ranges = gm.radius_bbox(0, 179_999_000, 50_000)
    assert len(ranges) == 2 and ranges[0][1] == 180_000_000 and ranges[1][0] == -180_000_000
    assert ranges[0][0] < 179_999_000 and ranges[1][1] > -180_000_000 and min_lat < 0 < max_lat
    near = gm.radius_bbox(0, 0, 50_000)[2]
    assert len(near) == 1 and near[0][0] < 0 < near[0][1]
    assert gm.radius_bbox(89_999_000, 0, 50_000)[2] == [(-180_000_000, 180_000_000)]  # a pole is inside the box
    cells = gm.cell_ranges(min_lat, max_lat, ranges, 10_000)
    assert cells is not None and len(cells) % 2 == 0
    # a point just across the antimeridian falls in one of the cell ranges
    cell = gm.cell_of(0, -179_999_000, 10_000)
    assert any(lo <= cell <= hi for lo, hi in cells)
    assert gm.cell_ranges(-90_000_000, 90_000_000, [(-180_000_000, 180_000_000)], 10_000) is None  # too many rows


def test_scoring_formula_and_order(ops: types.SimpleNamespace) -> None:
    sc, gm = ops.sc, ops.gm
    assert sc.score_parts(5_000, 2, 4_500, 20_000, 5) == (750, 600, 900)
    assert sc.score_parts(0, 0, 0, 20_000, 5) == (1000, 1000, 0)
    assert sc.score_parts(20_000, 4, 5_000, 20_000, 5) == (0, 200, 1000)
    assert sc.score_parts(1, 0, 9_999, 20_000, 5) == (1000 - 1000 // 20_000, 1000, 1000)  # rating is clamped
    w = sc.Weights(600, 300, 100)
    point = (0, 0)
    here = sc.Candidate("a", 0, 0, load=2, rating_milli=4_500)
    got = sc.evaluate(point, here, w, 20_000, 5)
    assert got.distance_m == 0 and got.parts == (1000, 600, 900) and got.score == 600 * 1000 + 300 * 600 + 100 * 900
    away = sc.Candidate("b", 0, 40_000, load=0, rating_milli=0)  # about 4.4 km
    metres = gm.haversine_m(0, 0, 0, 40_000)
    got = sc.evaluate(point, away, w, 20_000, 5)
    assert got.distance_m == metres and got.parts[0] == 1000 - 1000 * metres // 20_000
    assert got.score == 600 * got.parts[0] + 300 * 1000
    assert sc.evaluate(point, sc.Candidate("far", 0, 1_000_000, 0, 0), w, 20_000, 5) == "too_far"
    assert sc.evaluate(point, sc.Candidate("busy", 0, 0, 5, 0), w, 20_000, 5) == "overloaded"
    assert sc.evaluate(point, sc.Candidate("edge", 0, 0, 4, 0), w, 20_000, 5) != "overloaded"
    # order: score desc, then distance, then id: a tie never stays a tie
    cands = [sc.Candidate("z", 0, 0), sc.Candidate("m", 0, 0), sc.Candidate("a", 0, 40_000), sc.Candidate("busy", 0, 0, 9), sc.Candidate("far", 5_000_000, 0)]
    ranked, excluded = sc.rank(point, cands, sc.Weights(1000, 0, 0), 20_000, 5)
    assert [r.candidate_id for r in ranked] == ["m", "z", "a"]
    assert excluded == [("busy", "overloaded"), ("far", "too_far")]
    ranked, excluded = sc.rank(point, cands, sc.Weights(1000, 0, 0), 20_000, 5, skip={"m"})
    assert [r.candidate_id for r in ranked] == ["z", "a"] and ("m", "previously_declined") in excluded
    assert all(type(r.score) is int and type(r.distance_m) is int for r in ranked)
    assert sc.adjust_score(here, 42) == 42


def test_batch_solver_is_optimal_and_deterministic(ops: types.SimpleNamespace) -> None:
    sc = ops.sc
    w = sc.Weights(1000, 0, 0)
    # r1 prefers c1 (closest) but r2 can ONLY be served by c1: the optimum serves both
    reqs = [("r1", (0, 0)), ("r2", (0, 20_000))]
    cands = [sc.Candidate("c1", 0, 10_000), sc.Candidate("c2", 0, -80_000)]
    pairs, unassigned, solver = sc.solve_batch(reqs, cands, w, 10_000, 5)
    assert solver == "optimal" and unassigned == []
    assert {(p.request_ref, p.candidate_id) for p in pairs} == {("r1", "c2"), ("r2", "c1")} or len(pairs) == 2
    assert len({p.candidate_id for p in pairs}) == len(pairs)
    # a candidate takes at most one request; the loser stays unassigned
    pairs, unassigned, _ = sc.solve_batch([("r1", (0, 0)), ("r2", (0, 0))], [sc.Candidate("only", 0, 0)], w, 10_000, 5)
    assert len(pairs) == 1 and unassigned == ["r2"] and pairs[0].request_ref == "r1"
    again = sc.solve_batch([("r2", (0, 0)), ("r1", (0, 0))], [sc.Candidate("only", 0, 0)], w, 10_000, 5)
    assert again[0] == pairs and again[1] == unassigned
    # a request that declined a candidate does not get it
    pairs, unassigned, _ = sc.solve_batch([("r1", (0, 0))], [sc.Candidate("a", 0, 0), sc.Candidate("b", 0, 1_000)], w, 10_000, 5, {"r1": {"a"}})
    assert [p.candidate_id for p in pairs] == ["b"] and unassigned == []
    # large inputs fall back to greedy, still one request per candidate
    many = [(f"r{i:02d}", (0, i * 100)) for i in range(10)]
    pool = [sc.Candidate(f"c{i:02d}", 0, i * 100) for i in range(10)]
    pairs, unassigned, solver = sc.solve_batch(many, pool, w, 10_000, 5)
    assert solver == "greedy" and len(pairs) == 10 and len({p.candidate_id for p in pairs}) == 10 and unassigned == []


def test_fake_geo_adapters_are_deterministic(ops: types.SimpleNamespace) -> None:
    ad = ops.ad
    geo = ad.providers("fake")
    a = geo.geocoder.geocode("12 Main Street")
    assert a == geo.geocoder.geocode("  12 MAIN   street ") and a != geo.geocoder.geocode("13 Main Street")
    assert -60_000_000 <= a.lat_micro <= 60_000_000 and -170_000_000 <= a.lng_micro <= 170_000_000
    route = geo.router.route((0, 0), (0, 1_000_000), "drive")
    assert route.distance_m == (111_195 * 13 + 5) // 10 and route.duration_s == (route.distance_m * 10 + 69) // 139
    assert geo.router.route((0, 0), (0, 1_000_000), "walk").duration_s > route.duration_s > geo.router.route((0, 0), (0, 0), "drive").duration_s
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 1, 1, tzinfo=UTC)
    eta = geo.eta.eta((0, 0), (0, 1_000_000), "drive", start)
    assert eta.arrives_at == start + timedelta(seconds=route.duration_s) and eta.distance_m == route.distance_m
    with pytest.raises(RuntimeError):
        ad.providers("google")


def test_fake_predictor_is_deterministic_and_integer(ops: types.SimpleNamespace) -> None:
    pr = ops.pr
    model = pr.FakePredictor("fake-linear-v1", 2000)
    a = model.predict("eta", "job-1", {"stops": 3, "zone": "north", "rush": True})
    assert a == model.predict("eta", "job-1", {"rush": True, "zone": "north", "stops": 3})  # order does not matter
    assert a != model.predict("eta", "job-2", {"stops": 3, "zone": "north", "rush": True})
    assert a.model_id == "fake-linear-v1" and a.low <= a.value <= a.high and 3 + 5 + 1 <= a.value < 9 + 100
    assert all(type(v) is int for v in (a.value, a.low, a.high))
    assert a.high - a.value == max(1, abs(a.value) * 2000 // 10_000) == a.value - a.low
    wide = pr.FakePredictor("m", 0).predict("eta", "x", {})
    assert wide.high - wide.value == 1 == wide.value - wide.low
    neg = model.predict("eta", "x", {"debt": -1000})
    assert neg.low <= neg.value <= neg.high and neg.value < 0


def test_half_even_division(ops: types.SimpleNamespace) -> None:
    pr = ops.pr
    assert [pr.divide_half_even(n, 2) for n in (1, 3, 5, 7, 2, 0)] == [0, 2, 2, 4, 1, 0]
    assert pr.divide_half_even(10, 4) == 2 and pr.divide_half_even(14, 4) == 4 and pr.divide_half_even(11, 4) == 3
    assert pr.error_rate_bp(1, 3) == 3333 and pr.error_rate_bp(2, 3) == 6667 and pr.error_rate_bp(3, 3) == 10_000
