"""Location routes (generated, pack operations.location). Every route needs sign-in; reads need one of READ_ROLES,
reports one of WRITE_ROLES (spec: packs.operations.location). Rules: app/operations/location/service.py."""

import typing as _t

import fastapi as _fa
from fastapi import Path, Query, Response

from app.auth.models import AuthUser
from app.db import SessionDep
from app.operations.common import role_dependency
from app.operations.location import config as _config
from app.operations.location import schemas as _s
from app.operations.location import service as _svc

NO_NUL = r"^[^\x00]*$"  # Postgres text cannot hold NUL: refuse it with a 422, not a 500

router = _fa.APIRouter(prefix="/location", tags=["location"])

Reader = _t.Annotated[AuthUser, role_dependency(_config.READ_ROLES)]
Writer = _t.Annotated[AuthUser, role_dependency(_config.WRITE_ROLES)]


@router.post("/positions", response_model=_s.PositionResult, status_code=201)
async def report_position(body: _s.PositionIn, response: Response, session: SessionDep, user: Writer) -> _s.PositionResult:
    result, applied = await _svc.report(session, user, body)
    if not applied:
        response.status_code = 200
    return result


@router.get("/positions", response_model=_s.BoxOut)
async def positions_in_box(
    session: SessionDep, user: Reader,
    min_lat_micro: _t.Annotated[int, Query()], min_lng_micro: _t.Annotated[int, Query()],
    max_lat_micro: _t.Annotated[int, Query()], max_lng_micro: _t.Annotated[int, Query()],
    subject_kind: _t.Annotated[str | None, Query(max_length=32, pattern=NO_NUL)] = None,
    limit: _t.Annotated[int, Query(ge=1, le=500)] = _config.BOX_CAP,
) -> _s.BoxOut:
    return await _svc.in_box(session, user, min_lat_micro, min_lng_micro, max_lat_micro, max_lng_micro, subject_kind, limit)


@router.get("/positions/{subject_id}", response_model=_s.PositionOut)
async def latest_position(subject_id: _t.Annotated[str, Path(max_length=128, pattern=NO_NUL)], session: SessionDep, user: Reader) -> _s.PositionOut:
    return await _svc.latest(session, user, subject_id)


@router.get("/positions/{subject_id}/history", response_model=_s.HistoryOut)
async def position_history(
    subject_id: _t.Annotated[str, Path(max_length=128, pattern=NO_NUL)], session: SessionDep, user: Reader, limit: _t.Annotated[int, Query(ge=1, le=500)] = 100
) -> _s.HistoryOut:
    return await _svc.history(session, user, subject_id, limit)
