"""HTTP routes for Photo (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.photos import PhotoRepository
from app.schemas.photos import PhotoCreate, PhotoRead, PhotoUpdate

router = _fa.APIRouter(prefix="/photos", tags=["photos"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin", "member")),
    "delete": _access.access_dependency(roles=("admin", "member")),
    "get": _access.access_dependency(roles=("admin", "member", "viewer")),
    "head": _access.access_dependency(roles=("admin", "member", "viewer")),
    "list": _access.access_dependency(roles=("admin", "member", "viewer")),
    "replace": _access.access_dependency(roles=("admin", "member")),
    "update": _access.access_dependency(roles=("admin", "member")),
}


@router.get("", response_model=_pagination.Page[PhotoRead])
async def list_photos(
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
) -> _pagination.Page[PhotoRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await PhotoRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[PhotoRead](
        items=[PhotoRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=PhotoRead)
async def get_photos(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> PhotoRead:
    item = await PhotoRepository(session, **access.repo_kwargs).get(item_id)
    return PhotoRead.model_validate(item)


@router.head("/{item_id}")
async def head_photos(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await PhotoRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Photo not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=PhotoRead, status_code=201)
async def create_photos(
    body: PhotoCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> PhotoRead:
    item = await PhotoRepository(session, **access.repo_kwargs).create(body.model_dump())
    return PhotoRead.model_validate(item)


@router.put("/{item_id}", response_model=PhotoRead)
async def replace_photos(
    item_id: _uuid.UUID, body: PhotoCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> PhotoRead:
    item = await PhotoRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return PhotoRead.model_validate(item)


@router.patch("/{item_id}", response_model=PhotoRead)
async def update_photos(
    item_id: _uuid.UUID, body: PhotoUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> PhotoRead:
    item = await PhotoRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return PhotoRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_photos(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await PhotoRepository(session, **access.repo_kwargs).delete(item_id)
