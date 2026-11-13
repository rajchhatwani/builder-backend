"""Prediction routes (generated, pack operations.prediction). Every route needs sign-in; reads need one of READ_ROLES,
writes one of WRITE_ROLES (spec: packs.operations.prediction). Rules: app/operations/prediction/service.py."""

import typing as _t
import uuid as _uuid

import fastapi as _fa
from fastapi import Query

from app.auth.models import AuthUser
from app.core.pagination import Page
from app.db import SessionDep
from app.operations.common import role_dependency
from app.operations.prediction import config as _config
from app.operations.prediction import schemas as _s
from app.operations.prediction import service as _svc

router = _fa.APIRouter(prefix="/prediction", tags=["prediction"])

Reader = _t.Annotated[AuthUser, role_dependency(_config.READ_ROLES)]
Writer = _t.Annotated[AuthUser, role_dependency(_config.WRITE_ROLES)]


@router.post("/predict", response_model=_s.RecordOut, status_code=201)
async def predict(body: _s.PredictIn, session: SessionDep, user: Writer) -> _s.RecordOut:
    return await _svc.predict(session, user, body)


@router.post("/records/{record_id}/actual", response_model=_s.RecordOut)
async def record_actual(record_id: _uuid.UUID, body: _s.ActualIn, session: SessionDep, user: Writer) -> _s.RecordOut:
    return await _svc.record_actual(session, user, record_id, body)


@router.get("/records", response_model=Page[_s.RecordOut])
async def list_records(
    session: SessionDep, user: Reader,
    limit: _t.Annotated[int, Query(ge=1, le=200)] = 50, offset: _t.Annotated[int, Query(ge=0)] = 0,
    kind: _t.Annotated[str | None, Query(max_length=32)] = None,
    subject_ref: _t.Annotated[str | None, Query(max_length=128)] = None,
    has_actual: bool | None = None,
) -> Page[_s.RecordOut]:
    items, total = await _svc.list_records(session, user, limit, offset, kind, subject_ref, has_actual)
    return Page[_s.RecordOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/records/{record_id}", response_model=_s.RecordOut)
async def get_record(record_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.RecordOut:
    return await _svc.get_record(session, user, record_id)


@router.get("/stats", response_model=_s.StatsOut)
async def stats(
    session: SessionDep, user: Reader,
    kind: _t.Annotated[str | None, Query(max_length=32)] = None,
    model_id: _t.Annotated[str | None, Query(max_length=64)] = None,
) -> _s.StatsOut:
    return await _svc.stats(session, user, kind, model_id)
