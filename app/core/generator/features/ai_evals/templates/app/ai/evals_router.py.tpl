"""Eval harness routes (generated, pack ai.evals). Running a suite: evals.run_roles or the agents' approve_roles; reads: the
agents' read roles. Rules: app/ai/evals_service.py."""

import typing as _t
import uuid as _uuid

import fastapi as _fa
from fastapi import Depends, Query

from app.ai import agents_config as _agents
from app.ai import evals_config as _config
from app.ai import evals_schemas as _s
from app.ai import evals_service as _svc
from app.ai import service as _gateway
from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.core.errors import AppError
from app.core.pagination import Page
from app.db import SessionDep

router = _fa.APIRouter(prefix="/ai/evals", tags=["ai-evals"])


def _allow(user: AuthUser, *groups: tuple[str, ...]) -> AuthUser:
    """Allowed when any group is empty (= any signed-in user) or the caller has a role of any group."""
    if all(groups) and not any(_gateway.has_role(user, g) for g in groups):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    return user


async def _runner(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.RUN_ROLES, _agents.APPROVE_ROLES)


async def _reader(user: CurrentUser) -> AuthUser:
    groups = ([_agents.READ_ROLES] if _agents.READ_ROLES else []) + [_agents.APPROVE_ROLES, _agents.RUN_ROLES, _config.RUN_ROLES]
    return _allow(user, *groups)


Runner = _t.Annotated[AuthUser, Depends(_runner)]
Reader = _t.Annotated[AuthUser, Depends(_reader)]
Limit = _t.Annotated[int, Query(ge=1, le=200)]
Offset = _t.Annotated[int, Query(ge=0)]


@router.get("/suites", response_model=list[_s.SuiteOut])
async def list_suites(session: SessionDep, user: Reader) -> list[_s.SuiteOut]:
    return await _svc.list_suites(session, user)


@router.post("/suites/{suite}/run", response_model=_s.EvalRunOut, status_code=201)
async def run_suite(suite: _t.Annotated[str, _fa.Path(max_length=40)], session: SessionDep, user: Runner) -> _s.EvalRunOut:
    return await _svc.run_suite(session, user, suite)


@router.get("/runs", response_model=Page[_s.EvalRunOut])
async def list_runs(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    suite: _t.Annotated[str | None, Query(max_length=40)] = None,
) -> Page[_s.EvalRunOut]:
    items, total = await _svc.list_runs(session, user, limit, offset, suite)
    return Page[_s.EvalRunOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=_s.EvalRunOut)
async def get_run(run_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.EvalRunOut:
    return await _svc.get_run(session, user, run_id)
