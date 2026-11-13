"""Geo routes (generated, pack operations.geo). Every route needs sign-in; reads need one of READ_ROLES, writes one
of WRITE_ROLES (spec: packs.operations.geo). Rules: app/operations/geo/service.py."""

import typing as _t
import uuid as _uuid

import fastapi as _fa
from fastapi import Query, Response

from app.auth.models import AuthUser
from app.core.pagination import Page
from app.db import SessionDep
from app.operations.common import role_dependency
from app.operations.geo import config as _config
from app.operations.geo import schemas as _s
from app.operations.geo import service as _svc
from app.operations.points import query_point

router = _fa.APIRouter(prefix="/geo", tags=["geo"])

Reader = _t.Annotated[AuthUser, role_dependency(_config.READ_ROLES)]
Writer = _t.Annotated[AuthUser, role_dependency(_config.WRITE_ROLES)]
Limit = _t.Annotated[int, Query(ge=1, le=200)]
Offset = _t.Annotated[int, Query(ge=0)]


def _point(
    lat_micro: _t.Annotated[int | None, Query()] = None,
    lng_micro: _t.Annotated[int | None, Query()] = None,
    lat: _t.Annotated[str | None, Query(max_length=32)] = None,
    lng: _t.Annotated[str | None, Query(max_length=32)] = None,
) -> tuple[int, int]:
    return query_point(lat_micro, lng_micro, lat, lng)


QueryPoint = _t.Annotated[tuple[int, int], _fa.Depends(_point)]


@router.post("/places", response_model=_s.PlaceOut, status_code=201)
async def create_place(body: _s.PlaceCreate, session: SessionDep, user: Writer) -> _s.PlaceOut:
    return await _svc.create_place(session, user, body)


@router.get("/places", response_model=Page[_s.PlaceOut])
async def list_places(
    session: SessionDep, user: Reader, limit: Limit = 50, offset: Offset = 0, kind: _t.Annotated[str | None, Query(max_length=32)] = None
) -> Page[_s.PlaceOut]:
    items, total = await _svc.list_places(session, user, limit, offset, kind)
    return Page[_s.PlaceOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/places/within", response_model=_s.PlaceHits)
async def places_within(
    session: SessionDep, user: Reader, point: QueryPoint, radius_m: _t.Annotated[int, Query()],
    limit: Limit = 50, kind: _t.Annotated[str | None, Query(max_length=32)] = None,
) -> _s.PlaceHits:
    return await _svc.places_within(session, user, point, radius_m, limit, kind)


@router.get("/places/nearest", response_model=_s.PlaceHits)
async def places_nearest(
    session: SessionDep, user: Reader, point: QueryPoint,
    n: _t.Annotated[int, Query(ge=1, le=50)] = 5, kind: _t.Annotated[str | None, Query(max_length=32)] = None,
) -> _s.PlaceHits:
    return await _svc.places_nearest(session, user, point, n, kind)


@router.get("/places/{place_id}", response_model=_s.PlaceOut)
async def get_place(place_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.PlaceOut:
    return await _svc.get_place(session, user, place_id)


@router.delete("/places/{place_id}", status_code=204)
async def delete_place(place_id: _uuid.UUID, session: SessionDep, user: Writer) -> Response:
    await _svc.delete_place(session, user, place_id)
    return Response(status_code=204)


@router.post("/geofences", response_model=_s.GeofenceOut, status_code=201)
async def create_geofence(body: _s.GeofenceCreate, session: SessionDep, user: Writer) -> _s.GeofenceOut:
    return await _svc.create_geofence(session, user, body)


@router.get("/geofences", response_model=Page[_s.GeofenceOut])
async def list_geofences(session: SessionDep, user: Reader, limit: Limit = 50, offset: Offset = 0) -> Page[_s.GeofenceOut]:
    items, total = await _svc.list_geofences(session, user, limit, offset)
    return Page[_s.GeofenceOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/geofences/{fence_id}", response_model=_s.GeofenceOut)
async def get_geofence(fence_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.GeofenceOut:
    return await _svc.get_geofence(session, user, fence_id)


@router.delete("/geofences/{fence_id}", status_code=204)
async def delete_geofence(fence_id: _uuid.UUID, session: SessionDep, user: Writer) -> Response:
    await _svc.delete_geofence(session, user, fence_id)
    return Response(status_code=204)


@router.post("/contains", response_model=_s.Geofences)
async def contains(body: _s.ContainsIn, session: SessionDep, user: Reader) -> _s.Geofences:
    return await _svc.contains(session, user, body.point.micro)


@router.post("/distance", response_model=_s.DistanceOut)
async def distance(body: _s.DistanceIn, user: Reader) -> _s.DistanceOut:
    return _svc.distance(body.a.micro, body.b.micro)


@router.post("/evaluate", response_model=_s.EvaluateOut)
async def evaluate(body: _s.EvaluateIn, session: SessionDep, user: Writer) -> _s.EvaluateOut:
    return await _svc.evaluate(session, user, body)


@router.get("/events", response_model=Page[_s.FenceEventOut])
async def list_events(
    session: SessionDep, user: Reader, limit: Limit = 50, offset: Offset = 0,
    subject_id: _t.Annotated[str | None, Query(max_length=128)] = None, geofence_id: _uuid.UUID | None = None,
) -> Page[_s.FenceEventOut]:
    items, total = await _svc.list_events(session, user, limit, offset, subject_id, geofence_id)
    return Page[_s.FenceEventOut](items=items, total=total, limit=limit, offset=offset)


@router.post("/geocode", response_model=_s.GeocodeOut)
async def geocode(body: _s.GeocodeIn, user: Reader) -> _s.GeocodeOut:
    return _svc.geocode(body)


@router.post("/route", response_model=_s.RouteOut)
async def route(body: _s.RouteIn, user: Reader) -> _s.RouteOut:
    return _svc.route(body)


@router.post("/eta", response_model=_s.EtaOut)
async def eta(body: _s.EtaIn, user: Reader) -> _s.EtaOut:
    return _svc.eta(body)
