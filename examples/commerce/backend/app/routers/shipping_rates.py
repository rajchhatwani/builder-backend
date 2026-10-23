"""HTTP routes for ShippingRate (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.shipping_rates import ShippingRateRepository
from app.schemas.shipping_rates import ShippingRateCreate, ShippingRateRead, ShippingRateUpdate

router = _fa.APIRouter(prefix="/shipping_rates", tags=["shipping_rates"])

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


@router.get("", response_model=_pagination.Page[ShippingRateRead])
async def list_shipping_rates(
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
) -> _pagination.Page[ShippingRateRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await ShippingRateRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[ShippingRateRead](
        items=[ShippingRateRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ShippingRateRead)
async def get_shipping_rates(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> ShippingRateRead:
    item = await ShippingRateRepository(session, **access.repo_kwargs).get(item_id)
    return ShippingRateRead.model_validate(item)


@router.head("/{item_id}")
async def head_shipping_rates(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await ShippingRateRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("ShippingRate not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=ShippingRateRead, status_code=201)
async def create_shipping_rates(
    body: ShippingRateCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> ShippingRateRead:
    item = await ShippingRateRepository(session, **access.repo_kwargs).create(body.model_dump())
    return ShippingRateRead.model_validate(item)


@router.put("/{item_id}", response_model=ShippingRateRead)
async def replace_shipping_rates(
    item_id: _uuid.UUID, body: ShippingRateCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> ShippingRateRead:
    item = await ShippingRateRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return ShippingRateRead.model_validate(item)


@router.patch("/{item_id}", response_model=ShippingRateRead)
async def update_shipping_rates(
    item_id: _uuid.UUID, body: ShippingRateUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> ShippingRateRead:
    item = await ShippingRateRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return ShippingRateRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_shipping_rates(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await ShippingRateRepository(session, **access.repo_kwargs).delete(item_id)
