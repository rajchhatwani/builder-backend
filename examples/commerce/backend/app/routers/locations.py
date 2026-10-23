"""HTTP routes for Location (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.locations import LocationRepository
from app.schemas.locations import LocationCreate, LocationRead, LocationUpdate

router = _fa.APIRouter(prefix="/locations", tags=["locations"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("catalog", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("catalog", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("catalog", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[LocationRead])
async def list_locations(
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
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: name")
    ] = None,
    f_active: _t.Annotated[bool | None, _fa.Query(alias="active")] = None,
) -> _pagination.Page[LocationRead]:
    filters: dict[str, _t.Any] = {
        "active": f_active,
    }
    items, total = await LocationRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[LocationRead](
        items=[LocationRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=LocationRead)
async def get_locations(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> LocationRead:
    item = await LocationRepository(session, **access.repo_kwargs).get(item_id)
    return LocationRead.model_validate(item)


@router.head("/{item_id}")
async def head_locations(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await LocationRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Location not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=LocationRead, status_code=201)
async def create_locations(
    body: LocationCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> LocationRead:
    item = await LocationRepository(session, **access.repo_kwargs).create(body.model_dump())
    return LocationRead.model_validate(item)


@router.put("/{item_id}", response_model=LocationRead)
async def replace_locations(
    item_id: _uuid.UUID, body: LocationCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> LocationRead:
    item = await LocationRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return LocationRead.model_validate(item)


@router.patch("/{item_id}", response_model=LocationRead)
async def update_locations(
    item_id: _uuid.UUID, body: LocationUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> LocationRead:
    item = await LocationRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return LocationRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_locations(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await LocationRepository(session, **access.repo_kwargs).delete(item_id)
