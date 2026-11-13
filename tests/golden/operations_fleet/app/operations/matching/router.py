"""Matching routes (generated, pack operations.matching). Every route needs sign-in; reads need one of READ_ROLES,
assigning one of ASSIGN_ROLES (spec: packs.operations.matching). Rules: app/operations/matching/service.py."""

import typing as _t
import uuid as _uuid

import fastapi as _fa
from fastapi import Query

from app.auth.models import AuthUser
from app.core.pagination import Page
from app.db import SessionDep
from app.operations.common import role_dependency
from app.operations.matching import config as _config
from app.operations.matching import schemas as _s
from app.operations.matching import service as _svc

router = _fa.APIRouter(prefix="/matching", tags=["matching"])

Reader = _t.Annotated[AuthUser, role_dependency(_config.READ_ROLES)]
Assigner = _t.Annotated[AuthUser, role_dependency(_config.ASSIGN_ROLES)]


@router.post("/rank", response_model=_s.RankOut)
async def rank(body: _s.RankIn, session: SessionDep, user: Reader) -> _s.RankOut:
    return await _svc.rank(session, user, body)


@router.post("/assignments", response_model=_s.AssignmentOut, status_code=201)
async def assign(body: _s.AssignIn, session: SessionDep, user: Assigner) -> _s.AssignmentOut:
    return await _svc.assign(session, user, body)


@router.post("/batch", response_model=_s.BatchOut)
async def batch(body: _s.BatchIn, session: SessionDep, user: Assigner) -> _s.BatchOut:
    return await _svc.batch(session, user, body)


@router.get("/assignments", response_model=Page[_s.AssignmentOut])
async def list_assignments(
    session: SessionDep, user: Reader,
    limit: _t.Annotated[int, Query(ge=1, le=200)] = 50, offset: _t.Annotated[int, Query(ge=0)] = 0,
    status: _t.Annotated[_s.Status | None, Query()] = None,
    request_ref: _t.Annotated[str | None, Query(max_length=128)] = None,
    candidate_id: _t.Annotated[str | None, Query(max_length=128)] = None,
) -> Page[_s.AssignmentOut]:
    items, total = await _svc.list_assignments(session, user, limit, offset, status, request_ref, candidate_id)
    return Page[_s.AssignmentOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/assignments/{assignment_id}", response_model=_s.AssignmentOut)
async def get_assignment(assignment_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.AssignmentOut:
    return await _svc.get_assignment(session, user, assignment_id)


@router.post("/assignments/{assignment_id}/accept", response_model=_s.AssignmentOut)
async def accept(assignment_id: _uuid.UUID, session: SessionDep, user: Assigner) -> _s.AssignmentOut:
    return await _svc.accept(session, user, assignment_id)


@router.post("/assignments/{assignment_id}/reject", response_model=_s.AssignmentOut)
async def reject(assignment_id: _uuid.UUID, session: SessionDep, user: Assigner) -> _s.AssignmentOut:
    return await _svc.reject(session, user, assignment_id)


@router.post("/assignments/{assignment_id}/expire", response_model=_s.AssignmentOut)
async def expire(assignment_id: _uuid.UUID, session: SessionDep, user: Assigner) -> _s.AssignmentOut:
    return await _svc.expire(session, user, assignment_id)


@router.post("/expire-due", response_model=_s.ExpireOut)
async def expire_due(session: SessionDep, user: Assigner) -> _s.ExpireOut:
    return await _svc.expire_due(session, user)
