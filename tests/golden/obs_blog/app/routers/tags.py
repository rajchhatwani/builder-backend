"""HTTP routes for Tag (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.tags import TagRepository
from app.schemas.tags import TagCreate, TagRead, TagUpdate

router = _fa.APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=_pagination.Page[TagRead])
async def list_tags(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: none"),
    ] = None,
) -> _pagination.Page[TagRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await TagRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[TagRead](
        items=[TagRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=TagRead)
async def get_tags(item_id: _uuid.UUID, session: _db.SessionDep) -> TagRead:
    item = await TagRepository(session).get(item_id)
    return TagRead.model_validate(item)


@router.head("/{item_id}")
async def head_tags(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await TagRepository(session).exists(item_id):
        raise _errors.NotFoundError("Tag not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=TagRead, status_code=201)
async def create_tags(body: TagCreate, session: _db.SessionDep) -> TagRead:
    item = await TagRepository(session).create(body.model_dump())
    return TagRead.model_validate(item)


@router.put("/{item_id}", response_model=TagRead)
async def replace_tags(
    item_id: _uuid.UUID, body: TagCreate, session: _db.SessionDep
) -> TagRead:
    item = await TagRepository(session).replace(item_id, body.model_dump())
    return TagRead.model_validate(item)


@router.patch("/{item_id}", response_model=TagRead)
async def update_tags(
    item_id: _uuid.UUID, body: TagUpdate, session: _db.SessionDep
) -> TagRead:
    item = await TagRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return TagRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_tags(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await TagRepository(session).delete(item_id)
