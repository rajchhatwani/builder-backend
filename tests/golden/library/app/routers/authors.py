"""HTTP routes for Author (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.authors import AuthorRepository
from app.schemas.authors import AuthorCreate, AuthorRead, AuthorUpdate

router = _fa.APIRouter(prefix="/authors", tags=["authors"])


@router.get("", response_model=_pagination.Page[AuthorRead])
async def list_authors(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: name, rating"),
    ] = None,
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: name")
    ] = None,
    f_name: _t.Annotated[str | None, _fa.Query(alias="name")] = None,
) -> _pagination.Page[AuthorRead]:
    filters: dict[str, _t.Any] = {
        "name": f_name,
    }
    items, total = await AuthorRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[AuthorRead](
        items=[AuthorRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=AuthorRead)
async def get_authors(item_id: _uuid.UUID, session: _db.SessionDep) -> AuthorRead:
    item = await AuthorRepository(session).get(item_id)
    return AuthorRead.model_validate(item)


@router.head("/{item_id}")
async def head_authors(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await AuthorRepository(session).exists(item_id):
        raise _errors.NotFoundError("Author not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=AuthorRead, status_code=201)
async def create_authors(body: AuthorCreate, session: _db.SessionDep) -> AuthorRead:
    item = await AuthorRepository(session).create(body.model_dump())
    return AuthorRead.model_validate(item)


@router.put("/{item_id}", response_model=AuthorRead)
async def replace_authors(
    item_id: _uuid.UUID, body: AuthorCreate, session: _db.SessionDep
) -> AuthorRead:
    item = await AuthorRepository(session).replace(item_id, body.model_dump())
    return AuthorRead.model_validate(item)


@router.patch("/{item_id}", response_model=AuthorRead)
async def update_authors(
    item_id: _uuid.UUID, body: AuthorUpdate, session: _db.SessionDep
) -> AuthorRead:
    item = await AuthorRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return AuthorRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_authors(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await AuthorRepository(session).delete(item_id)
