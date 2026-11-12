"""Ledger routes (generated, pack money.ledger). Every route needs sign-in; reads need one of READ_ROLES and
writes one of POST_ROLES (spec: packs.money.ledger). See app/money/ledger/service.py for the rules."""

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
from app.money.ledger import config as _config
from app.money.ledger import schemas as _s
from app.money.ledger import service as _svc

router = _fa.APIRouter(prefix="/ledger", tags=["ledger"])


def _allow(user: AuthUser, roles: tuple[str, ...]) -> AuthUser:
    if roles and not effective_roles(user.roles) & set(roles):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    return user


async def _reader(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.READ_ROLES)


async def _poster(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.POST_ROLES)


Reader = _t.Annotated[AuthUser, Depends(_reader)]
Poster = _t.Annotated[AuthUser, Depends(_poster)]
Limit = _t.Annotated[int, Query(ge=1, le=200)]
Offset = _t.Annotated[int, Query(ge=0)]
REPLAYED = {"Idempotent-Replayed": "true"}


def _created(result: tuple[_s.TransactionOut, bool], response: Response) -> _s.TransactionOut:
    transaction, replayed = result
    if replayed:
        response.status_code = 200
        response.headers.update(REPLAYED)
    return transaction


@router.post("/accounts", response_model=_s.AccountOut, status_code=201)
async def create_account(body: _s.AccountCreate, session: SessionDep, user: Poster) -> _s.AccountOut:
    return await _svc.create_account(session, user, body)


@router.get("/accounts", response_model=Page[_s.AccountOut])
async def list_accounts(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    currency: _t.Annotated[str | None, Query(min_length=3, max_length=3)] = None,
) -> Page[_s.AccountOut]:
    items, total = await _svc.list_accounts(session, user, limit, offset, currency)
    return Page[_s.AccountOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/accounts/{account_id}/entries", response_model=Page[_s.AccountEntryOut])
async def account_entries(
    account_id: _uuid.UUID, session: SessionDep, user: Reader, limit: Limit = 50, offset: Offset = 0
) -> Page[_s.AccountEntryOut]:
    items, total = await _svc.account_entries(session, user, account_id, limit, offset)
    return Page[_s.AccountEntryOut](items=items, total=total, limit=limit, offset=offset)


@router.post("/transactions", response_model=_s.TransactionOut, status_code=201)
async def post_transaction(
    body: _s.TransactionIn, response: Response, session: SessionDep, user: Poster
) -> _s.TransactionOut:
    return _created(await _svc.post_transaction(session, user, body), response)


@router.get("/transactions", response_model=Page[_s.TransactionOut])
async def list_transactions(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    account_id: _uuid.UUID | None = None,
) -> Page[_s.TransactionOut]:
    items, total = await _svc.list_transactions(session, user, limit, offset, account_id)
    return Page[_s.TransactionOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/transactions/{transaction_id}", response_model=_s.TransactionOut)
async def get_transaction(transaction_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.TransactionOut:
    return await _svc.get_transaction(session, user, transaction_id)


@router.post("/transactions/{transaction_id}/reverse", response_model=_s.TransactionOut, status_code=201)
async def reverse_transaction(
    transaction_id: _uuid.UUID, body: _s.ReverseIn, response: Response, session: SessionDep, user: Poster
) -> _s.TransactionOut:
    return _created(await _svc.reverse_transaction(session, user, transaction_id, body), response)


@router.get("/balances", response_model=_s.BalancesOut)
async def balances(
    session: SessionDep,
    user: Reader,
    currency: _t.Annotated[str | None, Query(min_length=3, max_length=3)] = None,
) -> _s.BalancesOut:
    return await _svc.balances(session, user, currency)
