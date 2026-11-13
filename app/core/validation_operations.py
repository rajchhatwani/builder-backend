"""Validation for `packs.operations` (Cycle 5, Operations & geo pack: geo D13, location D14, matching D15,
prediction D16). Issues go through `add(path, code, message)`. Structure (unknown block or option, a float where an
integer is required) is refused by the spec models (extra=forbid, StrictInt); this module checks values and the
cross-section rules. Nothing here runs anything."""

from collections.abc import Callable

from app.core.spec_models import Spec

Add = Callable[[str, str, str], None]

GEO_TABLES = ("geo_places", "geo_geofences", "geo_memberships", "geo_events")
LOCATION_TABLES = ("location_positions", "location_history")
MATCHING_TABLES = ("match_assignments",)
PREDICTION_TABLES = ("prediction_records",)
OPERATIONS_BLOCKS = ("geo", "location", "matching", "prediction")
MAX_COORD_MICRO = 180_000_000


def operations_active(spec: Spec) -> bool:
    return spec.packs is not None and spec.packs.operations is not None


def _block(spec: Spec, name: str) -> object | None:
    return getattr(spec.packs.operations, name) if operations_active(spec) else None  # type: ignore[union-attr]


def geo_active(spec: Spec) -> bool:
    return _block(spec, "geo") is not None


def location_active(spec: Spec) -> bool:
    return _block(spec, "location") is not None


def matching_active(spec: Spec) -> bool:
    return _block(spec, "matching") is not None


def prediction_active(spec: Spec) -> bool:
    return _block(spec, "prediction") is not None


def operations_pack_ids(spec: Spec) -> tuple[str, ...]:
    """Dotted ids ("operations.geo", ...) of the declared operations blocks, sorted."""
    return tuple(sorted(f"operations.{b}" for b in OPERATIONS_BLOCKS if _block(spec, b) is not None))


def operations_tables(spec: Spec) -> tuple[str, ...]:
    out: tuple[str, ...] = ()
    if geo_active(spec):
        out += GEO_TABLES
    if location_active(spec):
        out += LOCATION_TABLES
    if matching_active(spec):
        out += MATCHING_TABLES
    if prediction_active(spec):
        out += PREDICTION_TABLES
    return out


def _check_needs(spec: Spec, add: Add, p: str, what: str) -> None:
    if spec.auth is None or not spec.auth.enabled:
        add(p, "needs_auth", f"{what} needs auth.enabled: every route needs a signed-in caller")
    elif spec.authorization is not None and spec.authorization.model != "rbac":
        add(p, "needs_rbac", f"{what} needs authorization.model rbac (it checks roles, not abac / pbac policies)")


def _check_roles(spec: Spec, add: Add, p: str, block: object, fields: tuple[str, ...]) -> None:
    if spec.auth is None:
        return
    known = {r.name for r in spec.auth.roles}
    for field in fields:
        for role in getattr(block, field):
            if role not in known:
                add(f"{p}.{field}", "unknown_role", f"role {role!r} is not an auth role")


def _range(add: Add, p: str, field: str, value: int, low: int, high: int, unit: str = "") -> None:
    if not low <= value <= high:
        add(f"{p}.{field}", "out_of_range", f"{low} .. {high}{unit}")


def _check_geo(spec: Spec, add: Add) -> None:
    geo = spec.packs.operations.geo  # type: ignore[union-attr]
    assert geo is not None
    p = "packs.operations.geo"
    _check_needs(spec, add, p, "geo")
    _check_roles(spec, add, p, geo, ("read_roles", "write_roles"))
    if geo.provider != "fake":
        add(f"{p}.provider", "unsupported_provider", "the only provider is 'fake' (deterministic, no outbound calls)")
    _range(add, p, "grid_cell_micro", geo.grid_cell_micro, 1000, 1_000_000, " micro-degrees")
    _range(add, p, "max_places", geo.max_places, 1, 10_000_000)
    _range(add, p, "max_geofences", geo.max_geofences, 1, 100_000)
    _range(add, p, "max_polygon_vertices", geo.max_polygon_vertices, 3, 1000)
    _range(add, p, "max_radius_m", geo.max_radius_m, 1, 20_037_509, " metres")


def _check_location(spec: Spec, add: Add) -> None:
    loc = spec.packs.operations.location  # type: ignore[union-attr]
    assert loc is not None
    p = "packs.operations.location"
    _check_needs(spec, add, p, "location")
    _check_roles(spec, add, p, loc, ("read_roles", "write_roles"))
    _range(add, p, "history_cap", loc.history_cap, 1, 10_000, " rows per subject")
    _range(add, p, "max_subjects", loc.max_subjects, 1, 10_000_000)


def _check_matching(spec: Spec, add: Add) -> None:
    mt = spec.packs.operations.matching  # type: ignore[union-attr]
    assert mt is not None
    p = "packs.operations.matching"
    _check_needs(spec, add, p, "matching")
    _check_roles(spec, add, p, mt, ("read_roles", "assign_roles"))
    w = mt.weights
    for name in ("distance", "load", "rating"):
        _range(add, f"{p}.weights", name, getattr(w, name), 0, 1_000_000)
    if w.distance + w.load + w.rating == 0:
        add(f"{p}.weights", "all_zero", "at least one weight must be above zero (every score would tie)")
    _range(add, p, "max_distance_m", mt.max_distance_m, 1, 20_037_509, " metres")
    _range(add, p, "max_load", mt.max_load, 1, 1_000_000)
    _range(add, p, "offer_ttl_seconds", mt.offer_ttl_seconds, 1, 86_400 * 30)


def _check_prediction(spec: Spec, add: Add) -> None:
    pr = spec.packs.operations.prediction  # type: ignore[union-attr]
    assert pr is not None
    p = "packs.operations.prediction"
    _check_needs(spec, add, p, "prediction")
    _check_roles(spec, add, p, pr, ("read_roles", "write_roles"))
    if not pr.model_id or len(pr.model_id) > 64 or not pr.model_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        add(f"{p}.model_id", "invalid_model_id", "1..64 characters: letters, digits, - _ .")
    if not pr.unit or len(pr.unit) > 16 or not pr.unit.replace("_", "").isalnum():
        add(f"{p}.unit", "invalid_unit", "1..16 characters: letters, digits, _")
    _range(add, p, "interval_bp", pr.interval_bp, 0, 100_000, " basis points")


def check_operations(spec: Spec, add: Add) -> None:
    if not operations_active(spec):
        return
    ops = spec.packs.operations  # type: ignore[union-attr]
    assert ops is not None
    if all(getattr(ops, b) is None for b in OPERATIONS_BLOCKS):
        add("packs.operations", "empty_pack", "packs.operations declares no block (geo, location, matching, prediction)")
        return
    if ops.geo is not None:
        _check_geo(spec, add)
    if ops.location is not None:
        _check_location(spec, add)
    if ops.matching is not None:
        _check_matching(spec, add)
    if ops.prediction is not None:
        _check_prediction(spec, add)
