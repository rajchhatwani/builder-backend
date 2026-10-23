"""HTTP routes for Order (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.orders import OrderRepository
from app.schemas.orders import OrderCreate, OrderRead, OrderUpdate

router = _fa.APIRouter(prefix="/orders", tags=["orders"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("fulfillment", "manager", "support"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[OrderRead])
async def list_orders(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: created_at, number, placed_at, total"),
    ] = None,
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: email, note")
    ] = None,
    f_email: _t.Annotated[str | None, _fa.Query(alias="email")] = None,
    f_financial_status: _t.Annotated[str | None, _fa.Query(alias="financial_status")] = None,
    f_fulfillment_status: _t.Annotated[str | None, _fa.Query(alias="fulfillment_status")] = None,
    f_number: _t.Annotated[int | None, _fa.Query(alias="number")] = None,
    f_source: _t.Annotated[str | None, _fa.Query(alias="source")] = None,
    f_status: _t.Annotated[str | None, _fa.Query(alias="status")] = None,
) -> _pagination.Page[OrderRead]:
    filters: dict[str, _t.Any] = {
        "email": f_email,
        "financial_status": f_financial_status,
        "fulfillment_status": f_fulfillment_status,
        "number": f_number,
        "source": f_source,
        "status": f_status,
    }
    items, total = await OrderRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[OrderRead](
        items=[OrderRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=OrderRead)
async def get_orders(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> OrderRead:
    item = await OrderRepository(session, **access.repo_kwargs).get(item_id)
    return OrderRead.model_validate(item)


@router.head("/{item_id}")
async def head_orders(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await OrderRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Order not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=OrderRead, status_code=201)
async def create_orders(
    body: OrderCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> OrderRead:
    item = await OrderRepository(session, **access.repo_kwargs).create(body.model_dump())
    return OrderRead.model_validate(item)


@router.patch("/{item_id}", response_model=OrderRead)
async def update_orders(
    item_id: _uuid.UUID, body: OrderUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> OrderRead:
    item = await OrderRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return OrderRead.model_validate(item)
