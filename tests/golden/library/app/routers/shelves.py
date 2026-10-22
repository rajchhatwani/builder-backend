"""HTTP routes for Shelf (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import pagination as _pagination
from app.crud.shelves import ShelfRepository
from app.schemas.shelves import ShelfCreate, ShelfRead

router = _fa.APIRouter(prefix="/shelves", tags=["shelves"])


@router.get("", response_model=_pagination.Page[ShelfRead])
async def list_shelves(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: none"),
    ] = None,
    f_label: _t.Annotated[str | None, _fa.Query(alias="label")] = None,
) -> _pagination.Page[ShelfRead]:
    filters: dict[str, _t.Any] = {
        "label": f_label,
    }
    items, total = await ShelfRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[ShelfRead](
        items=[ShelfRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ShelfRead)
async def get_shelves(item_id: _uuid.UUID, session: _db.SessionDep) -> ShelfRead:
    item = await ShelfRepository(session).get(item_id)
    return ShelfRead.model_validate(item)


@router.post("", response_model=ShelfRead, status_code=201)
async def create_shelves(body: ShelfCreate, session: _db.SessionDep) -> ShelfRead:
    item = await ShelfRepository(session).create(body.model_dump())
    return ShelfRead.model_validate(item)
