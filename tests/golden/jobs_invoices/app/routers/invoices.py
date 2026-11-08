"""HTTP routes for Invoice (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.invoices import InvoiceRepository
from app.schemas.invoices import InvoiceCreate, InvoiceRead, InvoiceUpdate

router = _fa.APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("", response_model=_pagination.Page[InvoiceRead])
async def list_invoices(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: created_at"),
    ] = None,
) -> _pagination.Page[InvoiceRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await InvoiceRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[InvoiceRead](
        items=[InvoiceRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=InvoiceRead)
async def get_invoices(item_id: _uuid.UUID, session: _db.SessionDep) -> InvoiceRead:
    item = await InvoiceRepository(session).get(item_id)
    return InvoiceRead.model_validate(item)


@router.head("/{item_id}")
async def head_invoices(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await InvoiceRepository(session).exists(item_id):
        raise _errors.NotFoundError("Invoice not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=InvoiceRead, status_code=201)
async def create_invoices(body: InvoiceCreate, session: _db.SessionDep) -> InvoiceRead:
    item = await InvoiceRepository(session).create(body.model_dump())
    return InvoiceRead.model_validate(item)


@router.put("/{item_id}", response_model=InvoiceRead)
async def replace_invoices(
    item_id: _uuid.UUID, body: InvoiceCreate, session: _db.SessionDep
) -> InvoiceRead:
    item = await InvoiceRepository(session).replace(item_id, body.model_dump())
    return InvoiceRead.model_validate(item)


@router.patch("/{item_id}", response_model=InvoiceRead)
async def update_invoices(
    item_id: _uuid.UUID, body: InvoiceUpdate, session: _db.SessionDep
) -> InvoiceRead:
    item = await InvoiceRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return InvoiceRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_invoices(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await InvoiceRepository(session).delete(item_id)
