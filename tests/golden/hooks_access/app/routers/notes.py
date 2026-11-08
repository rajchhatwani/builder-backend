"""HTTP routes for Note (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.notes import NoteRepository
from app.schemas.notes import NoteCreate, NoteRead, NoteUpdate

router = _fa.APIRouter(prefix="/notes", tags=["notes"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin", "member"), stamp=True, authenticate=True, tenant=True),
    "delete": _access.access_dependency(authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("admin", "member"), owner=True, admin_sees_all=True, authenticate=True, tenant=True),
    "head": _access.access_dependency(authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("admin", "member"), owner=True, admin_sees_all=True, authenticate=True, tenant=True),
    "replace": _access.access_dependency(authenticate=True, tenant=True),
    "update": _access.access_dependency(authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[NoteRead])
async def list_notes(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: none"),
    ] = None,
) -> _pagination.Page[NoteRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await NoteRepository(session, **access.repo_kwargs).list_items(
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
async def get_notes(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> NoteRead:
    item = await NoteRepository(session, **access.repo_kwargs).get(item_id)
    return NoteRead.model_validate(item)


@router.head("/{item_id}")
async def head_notes(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await NoteRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Note not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=NoteRead, status_code=201)
async def create_notes(
    body: NoteCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> NoteRead:
    item = await NoteRepository(session, **access.repo_kwargs).create(body.model_dump())
    return NoteRead.model_validate(item)


@router.put("/{item_id}", response_model=NoteRead)
async def replace_notes(
    item_id: _uuid.UUID, body: NoteCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> NoteRead:
    item = await NoteRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return NoteRead.model_validate(item)


@router.patch("/{item_id}", response_model=NoteRead)
async def update_notes(
    item_id: _uuid.UUID, body: NoteUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> NoteRead:
    item = await NoteRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return NoteRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_notes(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await NoteRepository(session, **access.repo_kwargs).delete(item_id)
