"""Reconciliation routes (generated, pack money.reconciliation). Every route needs sign-in; reads need one of
READ_ROLES, writes one of RUN_ROLES (spec: packs.money.reconciliation). Rules: app/money/reconciliation/service.py."""

import typing as _t
import uuid as _uuid

import fastapi as _fa
from fastapi import Depends, Query, Response

from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.auth.service import effective_roles
from app.core.errors import AppError
from app.core.pagination import Page
from app.db import SessionDep
from app.money.reconciliation import config as _config
from app.money.reconciliation import schemas as _s
from app.money.reconciliation import service as _svc

router = _fa.APIRouter(prefix="/reconciliation", tags=["reconciliation"])


def _allow(user: AuthUser, roles: tuple[str, ...]) -> AuthUser:
    if roles and not effective_roles(user.roles) & set(roles):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    return user


async def _reader(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.READ_ROLES)


async def _runner(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.RUN_ROLES)


Reader = _t.Annotated[AuthUser, Depends(_reader)]
Runner = _t.Annotated[AuthUser, Depends(_runner)]
Limit = _t.Annotated[int, Query(ge=1, le=200)]
Offset = _t.Annotated[int, Query(ge=0)]
REPLAYED = {"Idempotent-Replayed": "true"}


@router.post("/runs", response_model=_s.RunOut, status_code=201)
async def import_run(body: _s.RunCreate, response: Response, session: SessionDep, user: Runner) -> _s.RunOut:
    run, replayed = await _svc.import_run(session, user, body)
    if replayed:
        response.status_code = 200
        response.headers.update(REPLAYED)
    return run


@router.get("/runs", response_model=Page[_s.RunOut])
async def list_runs(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    status: _t.Annotated[_t.Literal["open", "closed"] | None, Query()] = None,
) -> Page[_s.RunOut]:
    items, total = await _svc.list_runs(session, user, limit, offset, status)
    return Page[_s.RunOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=_s.RunOut)
async def get_run(run_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.RunOut:
    return await _svc.get_run(session, user, run_id)


@router.post("/runs/{run_id}/lines", response_model=_s.LinesAddedOut)
async def add_lines(run_id: _uuid.UUID, body: _s.LinesAdd, session: SessionDep, user: Runner) -> _s.LinesAddedOut:
    return await _svc.add_lines(session, user, run_id, body)


@router.post("/runs/{run_id}/match", response_model=_s.AutoMatchOut)
async def auto_match(run_id: _uuid.UUID, session: SessionDep, user: Runner) -> _s.AutoMatchOut:
    return await _svc.auto_match(session, user, run_id)


@router.post("/runs/{run_id}/matches", response_model=_s.MatchOut, status_code=201)
async def manual_match(run_id: _uuid.UUID, body: _s.ManualMatchIn, session: SessionDep, user: Runner) -> _s.MatchOut:
    return await _svc.manual_match(session, user, run_id, body)


@router.delete("/runs/{run_id}/matches/{match_id}", response_model=_s.MatchOut)
async def unmatch(run_id: _uuid.UUID, match_id: _uuid.UUID, session: SessionDep, user: Runner) -> _s.MatchOut:
    return await _svc.unmatch(session, user, run_id, match_id)


@router.get("/runs/{run_id}/results", response_model=_s.ResultsOut)
async def results(run_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.ResultsOut:
    return await _svc.results(session, user, run_id)


@router.post("/runs/{run_id}/close", response_model=_s.RunOut)
async def close_run(run_id: _uuid.UUID, response: Response, session: SessionDep, user: Runner) -> _s.RunOut:
    run, replayed = await _svc.close_run(session, user, run_id)
    if replayed:
        response.headers.update(REPLAYED)
    return run
