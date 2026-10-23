"""HTTP routes for InventoryLevel (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.inventory_levels import InventoryLevelRepository
from app.schemas.inventory_levels import InventoryLevelCreate, InventoryLevelRead, InventoryLevelUpdate

router = _fa.APIRouter(prefix="/inventory_levels", tags=["inventory_levels"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("catalog", "fulfillment", "manager"), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("catalog", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("catalog", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("catalog", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("catalog", "fulfillment", "manager"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("catalog", "fulfillment", "manager"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[InventoryLevelRead])
async def list_inventory_levels(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: available, updated_at"),
    ] = None,
    f_available: _t.Annotated[int | None, _fa.Query(alias="available")] = None,
) -> _pagination.Page[InventoryLevelRead]:
    filters: dict[str, _t.Any] = {
        "available": f_available,
    }
    items, total = await InventoryLevelRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[InventoryLevelRead](
        items=[InventoryLevelRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=InventoryLevelRead)
async def get_inventory_levels(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> InventoryLevelRead:
    item = await InventoryLevelRepository(session, **access.repo_kwargs).get(item_id)
    return InventoryLevelRead.model_validate(item)


@router.head("/{item_id}")
async def head_inventory_levels(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await InventoryLevelRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("InventoryLevel not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=InventoryLevelRead, status_code=201)
async def create_inventory_levels(
    body: InventoryLevelCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> InventoryLevelRead:
    item = await InventoryLevelRepository(session, **access.repo_kwargs).create(body.model_dump())
    return InventoryLevelRead.model_validate(item)


@router.put("/{item_id}", response_model=InventoryLevelRead)
async def replace_inventory_levels(
    item_id: _uuid.UUID, body: InventoryLevelCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> InventoryLevelRead:
    item = await InventoryLevelRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return InventoryLevelRead.model_validate(item)


@router.patch("/{item_id}", response_model=InventoryLevelRead)
async def update_inventory_levels(
    item_id: _uuid.UUID, body: InventoryLevelUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> InventoryLevelRead:
    item = await InventoryLevelRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return InventoryLevelRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_inventory_levels(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await InventoryLevelRepository(session, **access.repo_kwargs).delete(item_id)
