"""HTTP routes for Note (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.notes import NoteRepository
from app.schemas.notes import NoteCreate, NoteRead, NoteUpdate

router = _fa.APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=_pagination.Page[NoteRead])
async def list_notes(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: none"),
    ] = None,
) -> _pagination.Page[NoteRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await NoteRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[NoteRead](
        items=[NoteRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=NoteRead)
async def get_notes(item_id: _uuid.UUID, session: _db.SessionDep) -> NoteRead:
    item = await NoteRepository(session).get(item_id)
    return NoteRead.model_validate(item)


@router.head("/{item_id}")
async def head_notes(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await NoteRepository(session).exists(item_id):
        raise _errors.NotFoundError("Note not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=NoteRead, status_code=201)
async def create_notes(body: NoteCreate, session: _db.SessionDep) -> NoteRead:
    item = await NoteRepository(session).create(body.model_dump())
    return NoteRead.model_validate(item)


@router.put("/{item_id}", response_model=NoteRead)
async def replace_notes(
    item_id: _uuid.UUID, body: NoteCreate, session: _db.SessionDep
) -> NoteRead:
    item = await NoteRepository(session).replace(item_id, body.model_dump())
    return NoteRead.model_validate(item)


@router.patch("/{item_id}", response_model=NoteRead)
async def update_notes(
    item_id: _uuid.UUID, body: NoteUpdate, session: _db.SessionDep
) -> NoteRead:
    item = await NoteRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return NoteRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_notes(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await NoteRepository(session).delete(item_id)
