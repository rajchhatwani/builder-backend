"""HTTP routes for Store (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import pagination as _pagination
from app.crud.stores import StoreRepository
from app.schemas.stores import StoreCreate, StoreRead, StoreUpdate

router = _fa.APIRouter(prefix="/stores", tags=["stores"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("catalog", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("catalog", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[StoreRead])
async def list_stores(
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
) -> _pagination.Page[StoreRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await StoreRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[StoreRead](
        items=[StoreRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=StoreRead)
async def get_stores(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> StoreRead:
    item = await StoreRepository(session, **access.repo_kwargs).get(item_id)
    return StoreRead.model_validate(item)


@router.post("", response_model=StoreRead, status_code=201)
async def create_stores(
    body: StoreCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> StoreRead:
    item = await StoreRepository(session, **access.repo_kwargs).create(body.model_dump())
    return StoreRead.model_validate(item)


@router.patch("/{item_id}", response_model=StoreRead)
async def update_stores(
    item_id: _uuid.UUID, body: StoreUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> StoreRead:
    item = await StoreRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return StoreRead.model_validate(item)
