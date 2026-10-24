"""HTTP routes for Comment (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.comments import CommentRepository
from app.schemas.comments import CommentCreate, CommentRead, CommentUpdate

router = _fa.APIRouter(prefix="/comments", tags=["comments"])


@router.get("", response_model=_pagination.Page[CommentRead])
async def list_comments(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: none"),
    ] = None,
) -> _pagination.Page[CommentRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await CommentRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[CommentRead](
        items=[CommentRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=CommentRead)
async def get_comments(item_id: _uuid.UUID, session: _db.SessionDep) -> CommentRead:
    item = await CommentRepository(session).get(item_id)
    return CommentRead.model_validate(item)


@router.head("/{item_id}")
async def head_comments(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await CommentRepository(session).exists(item_id):
        raise _errors.NotFoundError("Comment not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=CommentRead, status_code=201)
async def create_comments(body: CommentCreate, session: _db.SessionDep) -> CommentRead:
    item = await CommentRepository(session).create(body.model_dump())
    return CommentRead.model_validate(item)


@router.put("/{item_id}", response_model=CommentRead)
async def replace_comments(
    item_id: _uuid.UUID, body: CommentCreate, session: _db.SessionDep
) -> CommentRead:
    item = await CommentRepository(session).replace(item_id, body.model_dump())
    return CommentRead.model_validate(item)


@router.patch("/{item_id}", response_model=CommentRead)
async def update_comments(
    item_id: _uuid.UUID, body: CommentUpdate, session: _db.SessionDep
) -> CommentRead:
    item = await CommentRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return CommentRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_comments(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await CommentRepository(session).delete(item_id)
