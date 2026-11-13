"""Agent runtime routes (generated, pack ai.agents). Roles come from the spec (packs.ai.agents.roles). Rules: app/ai/agents_service.py."""

import typing as _t
import uuid as _uuid

import fastapi as _fa
from fastapi import Depends, Query, Response

from app.ai import agents_config as _config
from app.ai import agents_schemas as _s
from app.ai import agents_service as _svc
from app.ai import service as _gateway
from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.core.errors import AppError
from app.core.pagination import Page
from app.db import SessionDep

router = _fa.APIRouter(prefix="/ai/agents", tags=["ai-agents"])


def _allow(user: AuthUser, *groups: tuple[str, ...]) -> AuthUser:
    """Allowed when any group is empty (= any signed-in user) or the caller has a role of any group."""
    if all(groups) and not any(_gateway.has_role(user, g) for g in groups):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    return user


async def _runner(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.RUN_ROLES)


async def _approver(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.APPROVE_ROLES)


async def _reader(user: CurrentUser) -> AuthUser:
    groups = ([_config.READ_ROLES] if _config.READ_ROLES else []) + [_config.APPROVE_ROLES, _config.RUN_ROLES]  # empty read_roles adds no reader
    return _allow(user, *groups)


Runner = _t.Annotated[AuthUser, Depends(_runner)]
Approver = _t.Annotated[AuthUser, Depends(_approver)]
Reader = _t.Annotated[AuthUser, Depends(_reader)]
Limit = _t.Annotated[int, Query(ge=1, le=200)]
Offset = _t.Annotated[int, Query(ge=0)]
AgentName = _t.Annotated[str, _fa.Path(max_length=40)]
AgentFilter = _t.Annotated[str | None, Query(max_length=40)]


# the fixed paths come before the {id} paths
@router.get("", response_model=_s.RegistryOut)
async def registry(session: SessionDep, user: Reader) -> _s.RegistryOut:
    return await _svc.registry(session, user)


@router.get("/runs", response_model=Page[_s.RunOut])
async def list_runs(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    agent: AgentFilter = None,
    status: _t.Annotated[_s.RunStatus | None, Query()] = None,
) -> Page[_s.RunOut]:
    items, total = await _svc.list_runs(session, user, limit, offset, agent, status)
    return Page[_s.RunOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=_s.RunOut)
async def get_run(run_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.RunOut:
    return await _svc.get_run(session, user, run_id)


@router.get("/proposals", response_model=Page[_s.ProposalOut])
async def list_proposals(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    status: _t.Annotated[_s.ProposalStatus | None, Query()] = None,
    agent: AgentFilter = None,
    run_id: _uuid.UUID | None = None,
) -> Page[_s.ProposalOut]:
    items, total = await _svc.list_proposals(session, user, limit, offset, status, agent, run_id)
    return Page[_s.ProposalOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/proposals/{proposal_id}", response_model=_s.ProposalOut)
async def get_proposal(proposal_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.ProposalOut:
    return await _svc.get_proposal(session, user, proposal_id)


@router.get("/stats", response_model=_s.StatsOut)
async def stats(session: SessionDep, user: Reader, agent: AgentFilter = None) -> _s.StatsOut:
    return await _svc.stats(session, user, agent)


@router.post("/{agent}/runs", response_model=_s.RunOut, status_code=201)
async def start_run(agent: AgentName, body: _s.RunIn, response: Response, session: SessionDep, user: Runner) -> _s.RunOut:
    out, replayed = await _svc.start_run(session, user, agent, body)
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return out


@router.post("/proposals/{proposal_id}/approve", response_model=_s.ProposalOut)
async def approve(
    proposal_id: _uuid.UUID, session: SessionDep, user: Approver, body: _s.ApproveIn | None = None
) -> _s.ProposalOut:
    return await _svc.approve(session, user, proposal_id, body.note if body is not None else None)


@router.post("/proposals/{proposal_id}/reject", response_model=_s.ProposalOut)
async def reject(proposal_id: _uuid.UUID, session: SessionDep, user: Approver, body: _s.RejectIn | None = None) -> _s.ProposalOut:
    return await _svc.reject(session, user, proposal_id, body.reason if body is not None else None)


@router.post("/proposals/{proposal_id}/acknowledge", response_model=_s.ProposalOut)
async def acknowledge(proposal_id: _uuid.UUID, session: SessionDep, user: Approver) -> _s.ProposalOut:
    return await _svc.acknowledge(session, user, proposal_id)


@router.post("/proposals/{proposal_id}/handoff", response_model=_s.ProposalOut)
async def handoff(proposal_id: _uuid.UUID, body: _s.HandoffIn, session: SessionDep, user: Approver) -> _s.ProposalOut:
    return await _svc.handoff(session, user, proposal_id, body.to_role, body.note)


@router.post("/proposals/{proposal_id}/outcome", response_model=_s.ProposalOut)
async def outcome(proposal_id: _uuid.UUID, body: _s.OutcomeIn, session: SessionDep, user: Approver) -> _s.ProposalOut:
    return await _svc.record_outcome(session, user, proposal_id, body.outcome, body.note)
