"""HTTP routes for Book (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.books import BookRepository
from app.schemas.books import BookCreate, BookRead, BookUpdate

router = _fa.APIRouter(prefix="/books", tags=["books"])


@router.get("", response_model=_pagination.Page[BookRead])
async def list_books(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(10, 50)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: pages, published_at, title"),
    ] = None,
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: isbn, title")
    ] = None,
    f_in_stock: _t.Annotated[bool | None, _fa.Query(alias="in_stock")] = None,
    f_pages: _t.Annotated[int | None, _fa.Query(alias="pages")] = None,
    f_status: _t.Annotated[str | None, _fa.Query(alias="status")] = None,
) -> _pagination.Page[BookRead]:
    filters: dict[str, _t.Any] = {
        "in_stock": f_in_stock,
        "pages": f_pages,
        "status": f_status,
    }
    items, total = await BookRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[BookRead](
        items=[BookRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=BookRead)
async def get_books(item_id: _uuid.UUID, session: _db.SessionDep) -> BookRead:
    item = await BookRepository(session).get(item_id)
    return BookRead.model_validate(item)


@router.head("/{item_id}")
async def head_books(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await BookRepository(session).exists(item_id):
        raise _errors.NotFoundError("Book not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=BookRead, status_code=201)
async def create_books(body: BookCreate, session: _db.SessionDep) -> BookRead:
    item = await BookRepository(session).create(body.model_dump())
    return BookRead.model_validate(item)


@router.put("/{item_id}", response_model=BookRead)
async def replace_books(
    item_id: _uuid.UUID, body: BookCreate, session: _db.SessionDep
) -> BookRead:
    item = await BookRepository(session).replace(item_id, body.model_dump())
    return BookRead.model_validate(item)


@router.patch("/{item_id}", response_model=BookRead)
async def update_books(
    item_id: _uuid.UUID, body: BookUpdate, session: _db.SessionDep
) -> BookRead:
    item = await BookRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return BookRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_books(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await BookRepository(session).delete(item_id)
