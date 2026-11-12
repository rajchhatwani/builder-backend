"""Invoicing routes (generated, pack money.invoicing). Every route needs sign-in; reads need one of READ_ROLES,
writes one of WRITE_ROLES (spec: packs.money.invoicing). Rules: app/money/invoicing/service.py."""

import datetime as _dt
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
from app.money.invoicing import schemas as _s
from app.money.invoicing import service as _svc

router = _fa.APIRouter(prefix="/invoices", tags=["invoices"])


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


@router.post("", response_model=_s.InvoiceOut, status_code=201)
async def create_invoice(body: _s.InvoiceCreate, session: SessionDep, user: Writer) -> _s.InvoiceOut:
    return await _svc.create_invoice(session, user, body)


@router.get("", response_model=Page[_s.InvoiceOut])
async def list_invoices(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    kind: _t.Annotated[_t.Literal["receivable", "payable"] | None, Query()] = None,
    status: _t.Annotated[_t.Literal["draft", "issued", "partially_paid", "paid", "void"] | None, Query()] = None,
    counterparty: _t.Annotated[str | None, Query(max_length=200)] = None,
) -> Page[_s.InvoiceOut]:
    items, total = await _svc.list_invoices(session, user, limit, offset, kind, status, counterparty)
    return Page[_s.InvoiceOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/aging", response_model=_s.AgingOut)
async def aging(
    session: SessionDep,
    user: Reader,
    kind: _t.Annotated[_t.Literal["receivable", "payable"], Query()] = "receivable",
    as_of: _dt.date | None = None,
) -> _s.AgingOut:
    return await _svc.aging(session, user, kind, as_of)


@router.get("/{invoice_id}", response_model=_s.InvoiceOut)
async def get_invoice(invoice_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.InvoiceOut:
    return await _svc.get_invoice(session, user, invoice_id)


@router.patch("/{invoice_id}", response_model=_s.InvoiceOut)
async def update_invoice(invoice_id: _uuid.UUID, body: _s.InvoiceUpdate, session: SessionDep, user: Writer) -> _s.InvoiceOut:
    return await _svc.update_invoice(session, user, invoice_id, body)


@router.post("/{invoice_id}/issue", response_model=_s.InvoiceOut)
async def issue_invoice(invoice_id: _uuid.UUID, session: SessionDep, user: Writer) -> _s.InvoiceOut:
    return await _svc.issue_invoice(session, user, invoice_id)


@router.post("/{invoice_id}/payments", response_model=_s.InvoiceOut, status_code=201)
async def record_payment(
    invoice_id: _uuid.UUID, body: _s.PaymentIn, response: Response, session: SessionDep, user: Writer
) -> _s.InvoiceOut:
    invoice, replayed = await _svc.record_payment(session, user, invoice_id, body)
    if replayed:
        response.status_code = 200
        response.headers.update(REPLAYED)
    return invoice


@router.post("/{invoice_id}/void", response_model=_s.InvoiceOut)
async def void_invoice(
    invoice_id: _uuid.UUID, response: Response, session: SessionDep, user: Writer, body: _s.VoidIn | None = None
) -> _s.InvoiceOut:
    invoice, replayed = await _svc.void_invoice(session, user, invoice_id, body or _s.VoidIn())
    if replayed:
        response.headers.update(REPLAYED)
    return invoice
