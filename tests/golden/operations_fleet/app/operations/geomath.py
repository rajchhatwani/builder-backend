"""Pure geo maths of the operations pack (generated). Coordinates are INTEGER micro-degrees (1e-6 degree); distances
are integer metres. No database, no network. The haversine uses the standard library's trigonometry on floats
internally and returns a rounded integer: nothing float leaves this module."""

import math
from collections.abc import Sequence

MICRO = 1_000_000
EARTH_RADIUS_M = 6_371_000
MAX_LAT_MICRO = 90 * MICRO
MAX_LNG_MICRO = 180 * MICRO
_METRES_PER_DEGREE = EARTH_RADIUS_M * math.pi / 180
MAX_CELL_ROWS = 512

Vertex = tuple[int, int]  # (lat_micro, lng_micro)


def valid_coordinates(lat_micro: int, lng_micro: int) -> bool:
    return -MAX_LAT_MICRO <= lat_micro <= MAX_LAT_MICRO and -MAX_LNG_MICRO <= lng_micro <= MAX_LNG_MICRO


def haversine_m(lat1: int, lng1: int, lat2: int, lng2: int) -> int:
    """Great-circle distance in whole metres (sphere of radius 6,371 km), rounded half up."""
    phi1, phi2 = math.radians(lat1 / MICRO), math.radians(lat2 / MICRO)
    dphi = phi2 - phi1
    dlambda = math.radians((lng2 - lng1) / MICRO)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    a = min(1.0, max(0.0, a))
    return int(2 * EARTH_RADIUS_M * math.asin(math.sqrt(a)) + 0.5)


# --- grid cell index ---------------------------------------------------------------------------------------


def cell_width(size: int) -> int:
    return 360 * MICRO // size + 2


def cell_of(lat_micro: int, lng_micro: int, size: int) -> int:
    """One integer per grid cell of `size` micro-degrees: row * width + column (non-negative)."""
    row = (lat_micro + MAX_LAT_MICRO) // size
    col = (lng_micro + MAX_LNG_MICRO) // size
    return row * cell_width(size) + col


def radius_bbox(lat_micro: int, lng_micro: int, radius_m: int) -> tuple[int, int, list[tuple[int, int]]]:
    """(min_lat, max_lat, longitude ranges) of a box that contains every point within `radius_m` of the centre.
    The longitude ranges are 1 or 2 (antimeridian) entries; the whole range when a pole is inside the box."""
    dlat = int(radius_m / _METRES_PER_DEGREE * MICRO) + 2
    min_lat, max_lat = max(-MAX_LAT_MICRO, lat_micro - dlat), min(MAX_LAT_MICRO, lat_micro + dlat)
    whole = [(-MAX_LNG_MICRO, MAX_LNG_MICRO)]
    if lat_micro - dlat <= -MAX_LAT_MICRO or lat_micro + dlat >= MAX_LAT_MICRO:
        return min_lat, max_lat, whole
    cos_lat = math.cos(math.radians(max(abs(min_lat), abs(max_lat)) / MICRO))
    if cos_lat < 1e-6:
        return min_lat, max_lat, whole
    dlng = int(radius_m / (_METRES_PER_DEGREE * cos_lat) * MICRO) + 2
    if dlng >= MAX_LNG_MICRO:
        return min_lat, max_lat, whole
    low, high = lng_micro - dlng, lng_micro + dlng
    if low < -MAX_LNG_MICRO:
        return min_lat, max_lat, [(low + 2 * MAX_LNG_MICRO, MAX_LNG_MICRO), (-MAX_LNG_MICRO, high)]
    if high > MAX_LNG_MICRO:
        return min_lat, max_lat, [(low, MAX_LNG_MICRO), (-MAX_LNG_MICRO, high - 2 * MAX_LNG_MICRO)]
    return min_lat, max_lat, [(low, high)]


def cell_ranges(min_lat: int, max_lat: int, lng_ranges: Sequence[tuple[int, int]], size: int) -> list[tuple[int, int]] | None:
    """Inclusive (low, high) cell-key ranges covering the box, one per grid row and longitude range; None when
    the box spans more than MAX_CELL_ROWS rows (the caller then filters on the coordinates only)."""
    row_lo = (min_lat + MAX_LAT_MICRO) // size
    row_hi = (max_lat + MAX_LAT_MICRO) // size
    if row_hi - row_lo + 1 > MAX_CELL_ROWS:
        return None
    width = cell_width(size)
    out: list[tuple[int, int]] = []
    for row in range(row_lo, row_hi + 1):
        for lng_lo, lng_hi in lng_ranges:
            out.append((row * width + (lng_lo + MAX_LNG_MICRO) // size, row * width + (lng_hi + MAX_LNG_MICRO) // size))
    return out


# --- polygons (integer arithmetic only) ----------------------------------------------------------------------


def _cross(o: Vertex, a: Vertex, b: Vertex) -> int:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p: Vertex, a: Vertex, b: Vertex) -> bool:
    return (
        _cross(a, b, p) == 0
        and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def segments_intersect(a: Vertex, b: Vertex, c: Vertex, d: Vertex) -> bool:
    """True when segments ab and cd share at least one point (touching counts)."""
    d1, d2, d3, d4 = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True
    return _on_segment(c, a, b) or _on_segment(d, a, b) or _on_segment(a, c, d) or _on_segment(b, c, d)


def polygon_area2(verts: Sequence[Vertex]) -> int:
    """Twice the signed area (shoelace), an integer."""
    return sum(
        verts[i][0] * verts[(i + 1) % len(verts)][1] - verts[(i + 1) % len(verts)][0] * verts[i][1]
        for i in range(len(verts))
    )


def polygon_problem(verts: Sequence[Vertex]) -> str | None:
    """None for a usable simple polygon, else the reason: too few vertices, repeated vertex, zero area,
    longitude span over 180 degrees (a polygon may not cross the antimeridian), or a self-intersection."""
    n = len(verts)
    if n < 3:
        return "a polygon needs at least 3 vertices"
    if len(set(verts)) != n:
        return "a vertex is repeated"
    if polygon_area2(verts) == 0:
        return "the polygon has no area"
    lngs = [v[1] for v in verts]
    if max(lngs) - min(lngs) > MAX_LNG_MICRO:
        return "a polygon may not span more than 180 degrees of longitude"
    for i in range(n):
        a, b, c = verts[i], verts[(i + 1) % n], verts[(i + 2) % n]
        if _cross(b, a, c) == 0 and (a[0] - b[0]) * (c[0] - b[0]) + (a[1] - b[1]) * (c[1] - b[1]) > 0:
            return "the polygon folds back on itself"
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # the first and the last edge meet at vertex 0 by design
            if segments_intersect(a, b, verts[j], verts[(j + 1) % n]):
                return "the polygon crosses itself"
    return None


def point_in_polygon(lat_micro: int, lng_micro: int, verts: Sequence[Vertex]) -> bool:
    """Ray casting on integers; a point on the border counts as inside."""
    p = (lat_micro, lng_micro)
    inside = False
    n = len(verts)
    for i in range(n):
        a, b = verts[i], verts[(i + 1) % n]
        if _on_segment(p, a, b):
            return True
        if (a[0] > lat_micro) != (b[0] > lat_micro):
            lhs = (lng_micro - a[1]) * (b[0] - a[0])
            rhs = (lat_micro - a[0]) * (b[1] - a[1])
            if (b[0] > a[0] and lhs < rhs) or (b[0] < a[0] and lhs > rhs):
                inside = not inside
    return inside


def point_in_circle(lat_micro: int, lng_micro: int, center_lat: int, center_lng: int, radius_m: int) -> bool:
    return haversine_m(lat_micro, lng_micro, center_lat, center_lng) <= radius_m
