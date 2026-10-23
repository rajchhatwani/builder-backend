"""HTTP routes for Post (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.posts import PostRepository
from app.schemas.posts import PostCreate, PostRead, PostUpdate

router = _fa.APIRouter(prefix="/posts", tags=["posts"])


@router.get("", response_model=_pagination.Page[PostRead])
async def list_posts(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: none"),
    ] = None,
) -> _pagination.Page[PostRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await PostRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[PostRead](
        items=[PostRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=PostRead)
async def get_posts(item_id: _uuid.UUID, session: _db.SessionDep) -> PostRead:
    item = await PostRepository(session).get(item_id)
    return PostRead.model_validate(item)


@router.head("/{item_id}")
async def head_posts(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await PostRepository(session).exists(item_id):
        raise _errors.NotFoundError("Post not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=PostRead, status_code=201)
async def create_posts(body: PostCreate, session: _db.SessionDep) -> PostRead:
    item = await PostRepository(session).create(body.model_dump())
    return PostRead.model_validate(item)


@router.put("/{item_id}", response_model=PostRead)
async def replace_posts(
    item_id: _uuid.UUID, body: PostCreate, session: _db.SessionDep
) -> PostRead:
    item = await PostRepository(session).replace(item_id, body.model_dump())
    return PostRead.model_validate(item)


@router.patch("/{item_id}", response_model=PostRead)
async def update_posts(
    item_id: _uuid.UUID, body: PostUpdate, session: _db.SessionDep
) -> PostRead:
    item = await PostRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return PostRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_posts(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await PostRepository(session).delete(item_id)
