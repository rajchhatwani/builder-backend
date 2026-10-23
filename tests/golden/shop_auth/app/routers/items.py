"""HTTP routes for Item (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.items import ItemRepository
from app.schemas.items import ItemCreate, ItemRead, ItemUpdate

router = _fa.APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=_pagination.Page[ItemRead])
async def list_items(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: none"),
    ] = None,
) -> _pagination.Page[ItemRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await ItemRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[ItemRead](
        items=[ItemRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ItemRead)
async def get_items(item_id: _uuid.UUID, session: _db.SessionDep) -> ItemRead:
    item = await ItemRepository(session).get(item_id)
    return ItemRead.model_validate(item)


@router.head("/{item_id}")
async def head_items(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await ItemRepository(session).exists(item_id):
        raise _errors.NotFoundError("Item not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=ItemRead, status_code=201)
async def create_items(body: ItemCreate, session: _db.SessionDep) -> ItemRead:
    item = await ItemRepository(session).create(body.model_dump())
    return ItemRead.model_validate(item)


@router.put("/{item_id}", response_model=ItemRead)
async def replace_items(
    item_id: _uuid.UUID, body: ItemCreate, session: _db.SessionDep
) -> ItemRead:
    item = await ItemRepository(session).replace(item_id, body.model_dump())
    return ItemRead.model_validate(item)


@router.patch("/{item_id}", response_model=ItemRead)
async def update_items(
    item_id: _uuid.UUID, body: ItemUpdate, session: _db.SessionDep
) -> ItemRead:
    item = await ItemRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return ItemRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_items(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await ItemRepository(session).delete(item_id)
