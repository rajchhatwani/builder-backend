"""Payout routes (generated, pack money.invoicing with `payouts`). Reads need one of READ_ROLES, running a payout
one of WRITE_ROLES (spec: packs.money.invoicing). Rules: app/money/invoicing/payouts_service.py."""

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
from app.money.invoicing import config as _config
from app.money.invoicing import payouts_service as _svc
from app.money.invoicing import schemas as _s

router = _fa.APIRouter(prefix="/payouts", tags=["payouts"])


def _allow(user: AuthUser, roles: tuple[str, ...]) -> AuthUser:
    if roles and not effective_roles(user.roles) & set(roles):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    return user


async def _reader(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.READ_ROLES)


async def _writer(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.WRITE_ROLES)


Reader = _t.Annotated[AuthUser, Depends(_reader)]
Writer = _t.Annotated[AuthUser, Depends(_writer)]
Limit = _t.Annotated[int, Query(ge=1, le=200)]
Offset = _t.Annotated[int, Query(ge=0)]
REPLAYED = {"Idempotent-Replayed": "true"}


@router.post("/run", response_model=_s.PayoutOut, status_code=201)
async def run_payout(body: _s.PayoutRunIn, response: Response, session: SessionDep, user: Writer) -> _s.PayoutOut:
    payout, replayed = await _svc.run_payout(session, user, body)
    if replayed:
        response.status_code = 200
        response.headers.update(REPLAYED)
    return payout


@router.get("", response_model=Page[_s.PayoutOut])
async def list_payouts(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    seller: _t.Annotated[str | None, Query(max_length=64)] = None,
    invoice_id: _uuid.UUID | None = None,
) -> Page[_s.PayoutOut]:
    items, total = await _svc.list_payouts(session, user, limit, offset, seller, invoice_id)
    return Page[_s.PayoutOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/totals", response_model=list[_s.PayoutTotalOut])
async def payout_totals(
    session: SessionDep, user: Reader, seller: _t.Annotated[str | None, Query(max_length=64)] = None
) -> list[_s.PayoutTotalOut]:
    return await _svc.totals(session, user, seller)


@router.get("/{payout_id}", response_model=_s.PayoutOut)
async def get_payout(payout_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.PayoutOut:
    return await _svc.get_payout(session, user, payout_id)
