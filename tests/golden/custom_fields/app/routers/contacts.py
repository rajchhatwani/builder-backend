"""HTTP routes for Contact (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.contacts import ContactRepository
from app.schemas.contacts import ContactCreate, ContactRead, ContactUpdate

router = _fa.APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=_pagination.Page[ContactRead])
async def list_contacts(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: none"),
    ] = None,
) -> _pagination.Page[ContactRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await ContactRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[ContactRead](
        items=[ContactRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ContactRead)
async def get_contacts(item_id: _uuid.UUID, session: _db.SessionDep) -> ContactRead:
    item = await ContactRepository(session).get(item_id)
    return ContactRead.model_validate(item)


@router.head("/{item_id}")
async def head_contacts(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await ContactRepository(session).exists(item_id):
        raise _errors.NotFoundError("Contact not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=ContactRead, status_code=201)
async def create_contacts(body: ContactCreate, session: _db.SessionDep) -> ContactRead:
    item = await ContactRepository(session).create(body.model_dump())
    return ContactRead.model_validate(item)


@router.put("/{item_id}", response_model=ContactRead)
async def replace_contacts(
    item_id: _uuid.UUID, body: ContactCreate, session: _db.SessionDep
) -> ContactRead:
    item = await ContactRepository(session).replace(item_id, body.model_dump())
    return ContactRead.model_validate(item)


@router.patch("/{item_id}", response_model=ContactRead)
async def update_contacts(
    item_id: _uuid.UUID, body: ContactUpdate, session: _db.SessionDep
) -> ContactRead:
    item = await ContactRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return ContactRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_contacts(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await ContactRepository(session).delete(item_id)
