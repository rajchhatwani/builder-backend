"""Geo service (generated). Places and geofences are tenant scoped; radius queries read only the grid cells (and the
coordinate box) around the point, then measure the haversine distance in integer metres and order by (distance, id).
Enter / exit evaluation is decided by the database: an enter is an INSERT ... ON CONFLICT DO NOTHING that returned a
row, an exit is a DELETE ... RETURNING, so two parallel evaluations never report the same transition twice."""

import typing as _t
import uuid as _uuid
from datetime import datetime

import sqlalchemy as _sa
from sqlalchemy.dialects import postgresql as _pg
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.operations import geomath as _gm
from app.operations.common import Tenant, scoped, tenant_of, tenant_values
from app.operations.geo import adapters as _adapters
from app.operations.geo import config as _config
from app.operations.geo import schemas as _s
from app.operations.geo.models import GeoEvent, GeoGeofence, GeoMembership, GeoPlace
from app.operations.points import PointOut, coords


def tenant(user: _t.Any) -> Tenant:
    return tenant_of(user, _config.MULTI_TENANT)


def place_out(row: GeoPlace) -> _s.PlaceOut:
    return _s.PlaceOut(id=row.id, name=row.name, kind=row.kind, created_at=row.created_at, **coords(row.lat_micro, row.lng_micro))


def _hit(row: GeoPlace, distance: int) -> _s.PlaceHit:
    return _s.PlaceHit(id=row.id, name=row.name, kind=row.kind, created_at=row.created_at, distance_m=distance, **coords(row.lat_micro, row.lng_micro))


def fence_out(row: GeoGeofence) -> _s.GeofenceOut:
    center = PointOut.of(row.center_lat_micro, row.center_lng_micro) if row.shape == "circle" and row.center_lat_micro is not None and row.center_lng_micro is not None else None
    vertices = [PointOut.of(lat, lng) for lat, lng in row.vertices] if row.vertices else None
    return _s.GeofenceOut(
        id=row.id, name=row.name, shape=_t.cast(_s.Shape, row.shape), center=center, radius_m=row.radius_m,
        vertices=vertices, created_at=row.created_at,
    )


def event_out(row: GeoEvent) -> _s.FenceEventOut:
    return _s.FenceEventOut(
        id=row.id, subject_id=row.subject_id, geofence_id=row.geofence_id, geofence_name=row.geofence_name,
        event=_t.cast(_t.Literal["enter", "exit"], row.event), lat_micro=row.lat_micro, lng_micro=row.lng_micro,
        occurred_at=row.occurred_at,
    )


async def _count(session: AsyncSession, model: _t.Any, tn: Tenant) -> int:
    return int((await session.execute(scoped(_sa.select(_sa.func.count()).select_from(model), model, tn))).scalar_one())


# --- places ----------------------------------------------------------------------------------------------


async def create_place(session: AsyncSession, user: _t.Any, body: _s.PlaceCreate) -> _s.PlaceOut:
    tn = tenant(user)
    if await _count(session, GeoPlace, tn) >= _config.MAX_PLACES:
        raise AppError("limit_reached", f"at most {_config.MAX_PLACES} places", 422)
    lat, lng = body.micro
    row = GeoPlace(
        name=body.name, kind=body.kind, lat_micro=lat, lng_micro=lng, cell=_gm.cell_of(lat, lng, _config.GRID_CELL_MICRO),
        **tenant_values(tn),
    )
    session.add(row)
    await session.commit()
    return place_out(row)


async def list_places(session: AsyncSession, user: _t.Any, limit: int, offset: int, kind: str | None) -> tuple[list[_s.PlaceOut], int]:
    tn = tenant(user)
    base = scoped(_sa.select(GeoPlace), GeoPlace, tn)
    if kind is not None:
        base = base.where(GeoPlace.kind == kind)
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await session.execute(base.order_by(GeoPlace.name, GeoPlace.id).limit(limit).offset(offset))).scalars()
    return [place_out(r) for r in rows], int(total)


async def get_place(session: AsyncSession, user: _t.Any, place_id: _uuid.UUID) -> _s.PlaceOut:
    row = (await session.execute(scoped(_sa.select(GeoPlace).where(GeoPlace.id == place_id), GeoPlace, tenant(user)))).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "place not found", 404)
    return place_out(row)


async def delete_place(session: AsyncSession, user: _t.Any, place_id: _uuid.UUID) -> None:
    result = await session.execute(scoped(_sa.delete(GeoPlace).where(GeoPlace.id == place_id), GeoPlace, tenant(user)))
    await session.commit()
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise AppError("not_found", "place not found", 404)


async def _scan(
    session: AsyncSession, tn: Tenant, lat: int, lng: int, radius_m: int, kind: str | None
) -> tuple[list[tuple[int, GeoPlace]], bool]:
    """Every place within `radius_m` of the point, as (distance, row) sorted by (distance, id), and whether the
    scan hit SCAN_CAP rows (then the answer may be incomplete)."""
    min_lat, max_lat, lng_ranges = _gm.radius_bbox(lat, lng, radius_m)
    stmt = scoped(_sa.select(GeoPlace), GeoPlace, tn).where(GeoPlace.lat_micro.between(min_lat, max_lat))
    stmt = stmt.where(_sa.or_(*[GeoPlace.lng_micro.between(lo, hi) for lo, hi in lng_ranges]))
    ranges = _gm.cell_ranges(min_lat, max_lat, lng_ranges, _config.GRID_CELL_MICRO)
    if ranges is not None:
        stmt = stmt.where(_sa.or_(*[GeoPlace.cell.between(lo, hi) for lo, hi in ranges]))
    if kind is not None:
        stmt = stmt.where(GeoPlace.kind == kind)
    rows = list((await session.execute(stmt.limit(_config.SCAN_CAP + 1))).scalars())
    truncated = len(rows) > _config.SCAN_CAP
    hits = []
    for row in rows[: _config.SCAN_CAP]:
        distance = _gm.haversine_m(lat, lng, row.lat_micro, row.lng_micro)
        if distance <= radius_m:
            hits.append((distance, row))
    hits.sort(key=lambda h: (h[0], str(h[1].id)))
    return hits, truncated


def _check_radius(radius_m: int) -> None:
    if not 1 <= radius_m <= _config.MAX_RADIUS_M:
        raise AppError("invalid_radius", f"radius_m must be 1..{_config.MAX_RADIUS_M}", 422)


async def places_within(
    session: AsyncSession, user: _t.Any, point: tuple[int, int], radius_m: int, limit: int, kind: str | None
) -> _s.PlaceHits:
    _check_radius(radius_m)
    hits, truncated = await _scan(session, tenant(user), point[0], point[1], radius_m, kind)
    return _s.PlaceHits(items=[_hit(r, d) for d, r in hits[:limit]], truncated=truncated or len(hits) > limit)


async def places_nearest(
    session: AsyncSession, user: _t.Any, point: tuple[int, int], n: int, kind: str | None
) -> _s.PlaceHits:
    """Widen the radius (x4 each round, from 1 km) until at least n places are inside it: all places within the
    radius were read, so the n closest of them are the n closest overall."""
    tn = tenant(user)
    radius = 1000
    truncated = False
    while True:
        radius = min(radius, _config.MAX_RADIUS_M)
        hits, truncated = await _scan(session, tn, point[0], point[1], radius, kind)
        if len(hits) >= n or radius >= _config.MAX_RADIUS_M:
            return _s.PlaceHits(items=[_hit(r, d) for d, r in hits[:n]], truncated=truncated)
        radius *= 4


# --- geofences -------------------------------------------------------------------------------------------


def _fence_box(shape: str, center: tuple[int, int] | None, radius: int | None, verts: list[_gm.Vertex]) -> tuple[int, int, int, int]:
    if shape == "polygon":
        return min(v[0] for v in verts), max(v[0] for v in verts), min(v[1] for v in verts), max(v[1] for v in verts)
    assert center is not None and radius is not None
    min_lat, max_lat, lng_ranges = _gm.radius_bbox(center[0], center[1], radius)
    if len(lng_ranges) == 1:
        return min_lat, max_lat, lng_ranges[0][0], lng_ranges[0][1]
    return min_lat, max_lat, -_gm.MAX_LNG_MICRO, _gm.MAX_LNG_MICRO  # crosses the antimeridian: no longitude prefilter


async def create_geofence(session: AsyncSession, user: _t.Any, body: _s.GeofenceCreate) -> _s.GeofenceOut:
    tn = tenant(user)
    if await _count(session, GeoGeofence, tn) >= _config.MAX_GEOFENCES:
        raise AppError("limit_reached", f"at most {_config.MAX_GEOFENCES} geofences", 422)
    center = body.center.micro if body.center is not None else None
    verts = [p.micro for p in body.vertices] if body.vertices is not None else []
    if body.shape == "circle":
        assert body.radius_m is not None
        if body.radius_m > _config.MAX_RADIUS_M:
            raise AppError("invalid_shape", f"radius_m must be 1..{_config.MAX_RADIUS_M}", 422)
    else:
        if len(verts) > _config.MAX_POLYGON_VERTICES:
            raise AppError("invalid_polygon", f"at most {_config.MAX_POLYGON_VERTICES} vertices", 422)
        problem = _gm.polygon_problem(verts)
        if problem is not None:
            raise AppError("invalid_polygon", problem, 422)
    min_lat, max_lat, min_lng, max_lng = _fence_box(body.shape, center, body.radius_m, verts)
    row = GeoGeofence(
        name=body.name, shape=body.shape,
        center_lat_micro=center[0] if center else None, center_lng_micro=center[1] if center else None,
        radius_m=body.radius_m if body.shape == "circle" else None,
        vertices=[list(v) for v in verts] if body.shape == "polygon" else None,
        min_lat_micro=min_lat, max_lat_micro=max_lat, min_lng_micro=min_lng, max_lng_micro=max_lng,
        **tenant_values(tn),
    )
    session.add(row)
    await session.commit()
    return fence_out(row)


async def list_geofences(session: AsyncSession, user: _t.Any, limit: int, offset: int) -> tuple[list[_s.GeofenceOut], int]:
    tn = tenant(user)
    base = scoped(_sa.select(GeoGeofence), GeoGeofence, tn)
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await session.execute(base.order_by(GeoGeofence.name, GeoGeofence.id).limit(limit).offset(offset))).scalars()
    return [fence_out(r) for r in rows], int(total)


async def get_geofence(session: AsyncSession, user: _t.Any, fence_id: _uuid.UUID) -> _s.GeofenceOut:
    stmt = scoped(_sa.select(GeoGeofence).where(GeoGeofence.id == fence_id), GeoGeofence, tenant(user))
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "geofence not found", 404)
    return fence_out(row)


async def delete_geofence(session: AsyncSession, user: _t.Any, fence_id: _uuid.UUID) -> None:
    result = await session.execute(scoped(_sa.delete(GeoGeofence).where(GeoGeofence.id == fence_id), GeoGeofence, tenant(user)))
    await session.commit()
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise AppError("not_found", "geofence not found", 404)


def _contains(row: GeoGeofence, lat: int, lng: int) -> bool:
    if row.shape == "circle":
        assert row.center_lat_micro is not None and row.center_lng_micro is not None and row.radius_m is not None
        return _gm.point_in_circle(lat, lng, row.center_lat_micro, row.center_lng_micro, row.radius_m)
    return _gm.point_in_polygon(lat, lng, [(int(v[0]), int(v[1])) for v in (row.vertices or [])])


async def fences_containing(session: AsyncSession, tn: Tenant, lat: int, lng: int) -> list[GeoGeofence]:
    stmt = scoped(_sa.select(GeoGeofence), GeoGeofence, tn).where(
        GeoGeofence.min_lat_micro <= lat, GeoGeofence.max_lat_micro >= lat,
        GeoGeofence.min_lng_micro <= lng, GeoGeofence.max_lng_micro >= lng,
    ).order_by(GeoGeofence.name, GeoGeofence.id)
    return [r for r in (await session.execute(stmt)).scalars() if _contains(r, lat, lng)]


async def contains(session: AsyncSession, user: _t.Any, point: tuple[int, int]) -> _s.Geofences:
    return _s.Geofences(items=[fence_out(r) for r in await fences_containing(session, tenant(user), *point)])


def distance(a: tuple[int, int], b: tuple[int, int]) -> _s.DistanceOut:
    return _s.DistanceOut(distance_m=_gm.haversine_m(*a, *b))


# --- enter / exit ----------------------------------------------------------------------------------------


async def evaluate_point(
    session: AsyncSession, tn: Tenant, subject_id: str, lat: int, lng: int, at: datetime | None = None
) -> tuple[list[_uuid.UUID], list[GeoEvent]]:
    """Compare the point with the subject's stored memberships. Does NOT commit (the caller does). Returns the
    ids of the fences the point is inside and the events of this call."""
    inside_rows = await fences_containing(session, tn, lat, lng)
    inside = {r.id: r for r in inside_rows}
    held = {
        row.geofence_id
        for row in (
            await session.execute(
                _sa.select(GeoMembership).where(
                    GeoMembership.subject_id == subject_id,
                    GeoMembership.geofence_id.in_(_sa.select(GeoGeofence.id).where(*([GeoGeofence.tenant_id == tn] if tn is not None else []))),
                )
            )
        ).scalars()
    }
    events: list[GeoEvent] = []
    stamp: dict[str, _t.Any] = {"occurred_at": at} if at is not None else {}
    for fence_id in sorted(set(inside) - held, key=str):
        fence = inside[fence_id]
        inserted = await session.execute(
            _pg.insert(GeoMembership)
            .values(subject_id=subject_id, geofence_id=fence_id, **tenant_values(tn))
            .on_conflict_do_nothing(constraint="uq_geo_memberships_subject_id_geofence_id")
            .returning(GeoMembership.id)
        )
        if inserted.first() is not None:
            events.append(GeoEvent(subject_id=subject_id, geofence_id=fence_id, geofence_name=fence.name, event="enter", lat_micro=lat, lng_micro=lng, **stamp, **tenant_values(tn)))
    for fence_id in sorted(held - set(inside), key=str):
        deleted = await session.execute(
            _sa.delete(GeoMembership)
            .where(GeoMembership.subject_id == subject_id, GeoMembership.geofence_id == fence_id)
            .returning(GeoMembership.id)
        )
        if deleted.first() is not None:
            name = (await session.execute(_sa.select(GeoGeofence.name).where(GeoGeofence.id == fence_id))).scalar_one_or_none()
            events.append(GeoEvent(subject_id=subject_id, geofence_id=fence_id, geofence_name=name or "", event="exit", lat_micro=lat, lng_micro=lng, **stamp, **tenant_values(tn)))
    session.add_all(events)
    await session.flush()
    return sorted(inside, key=str), events


async def evaluate(session: AsyncSession, user: _t.Any, body: _s.EvaluateIn) -> _s.EvaluateOut:
    lat, lng = body.point.micro
    inside, events = await evaluate_point(session, tenant(user), body.subject_id, lat, lng)
    out = _s.EvaluateOut(inside=inside, events=[event_out(e) for e in events])
    await session.commit()
    return out


async def list_events(
    session: AsyncSession, user: _t.Any, limit: int, offset: int, subject_id: str | None, geofence_id: _uuid.UUID | None
) -> tuple[list[_s.FenceEventOut], int]:
    base = scoped(_sa.select(GeoEvent), GeoEvent, tenant(user))
    if subject_id is not None:
        base = base.where(GeoEvent.subject_id == subject_id)
    if geofence_id is not None:
        base = base.where(GeoEvent.geofence_id == geofence_id)
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await session.execute(base.order_by(GeoEvent.occurred_at.desc(), GeoEvent.id).limit(limit).offset(offset))).scalars()
    return [event_out(r) for r in rows], int(total)


# --- adapters --------------------------------------------------------------------------------------------


def geocode(body: _s.GeocodeIn) -> _s.GeocodeOut:
    found = _adapters.providers(_config.PROVIDER).geocoder.geocode(body.address)
    return _s.GeocodeOut(provider=_config.PROVIDER, **coords(found.lat_micro, found.lng_micro))


def route(body: _s.RouteIn) -> _s.RouteOut:
    found = _adapters.providers(_config.PROVIDER).router.route(body.origin.micro, body.destination.micro, body.mode)
    return _s.RouteOut(distance_m=found.distance_m, duration_s=found.duration_s, mode=body.mode, provider=_config.PROVIDER)


def eta(body: _s.EtaIn) -> _s.EtaOut:
    found = _adapters.providers(_config.PROVIDER).eta.eta(body.origin.micro, body.destination.micro, body.mode, body.depart_at)
    return _s.EtaOut(duration_s=found.duration_s, distance_m=found.distance_m, arrives_at=found.arrives_at, provider=_config.PROVIDER)
