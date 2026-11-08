"""HTTP routes for Supplier (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.suppliers import SupplierRepository
from app.schemas.suppliers import SupplierCreate, SupplierRead, SupplierUpdate

router = _fa.APIRouter(prefix="/suppliers", tags=["suppliers"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin", "clerk")),
    "delete": _access.access_dependency(roles=("admin",)),
    "get": _access.access_dependency(roles=("admin", "approver", "clerk")),
    "list": _access.access_dependency(roles=("admin", "approver", "clerk")),
    "update": _access.access_dependency(roles=("admin",)),
}


@router.get("", response_model=_pagination.Page[SupplierRead])
async def list_suppliers(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: name"),
    ] = None,
    f_active: _t.Annotated[bool | None, _fa.Query(alias="active")] = None,
) -> _pagination.Page[SupplierRead]:
    filters: dict[str, _t.Any] = {
        "active": f_active,
    }
    items, total = await SupplierRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[SupplierRead](
        items=[SupplierRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=SupplierRead)
async def get_suppliers(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> SupplierRead:
    item = await SupplierRepository(session, **access.repo_kwargs).get(item_id)
    return SupplierRead.model_validate(item)


@router.head("/{item_id}")
async def head_suppliers(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await SupplierRepository(session).exists(item_id):
        raise _errors.NotFoundError("Supplier not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=SupplierRead, status_code=201)
async def create_suppliers(
    body: SupplierCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> SupplierRead:
    item = await SupplierRepository(session, **access.repo_kwargs).create(body.model_dump())
    return SupplierRead.model_validate(item)


@router.put("/{item_id}", response_model=SupplierRead)
async def replace_suppliers(
    item_id: _uuid.UUID, body: SupplierCreate, session: _db.SessionDep
) -> SupplierRead:
    item = await SupplierRepository(session).replace(item_id, body.model_dump())
    return SupplierRead.model_validate(item)


@router.patch("/{item_id}", response_model=SupplierRead)
async def update_suppliers(
    item_id: _uuid.UUID, body: SupplierUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> SupplierRead:
    item = await SupplierRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return SupplierRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_suppliers(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await SupplierRepository(session, **access.repo_kwargs).delete(item_id)
