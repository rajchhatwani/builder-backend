"""HTTP routes for OrderEvent (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import pagination as _pagination
from app.crud.order_events import OrderEventRepository
from app.schemas.order_events import OrderEventCreate, OrderEventRead

router = _fa.APIRouter(prefix="/order_events", tags=["order_events"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("fulfillment", "manager", "support"), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[OrderEventRead])
async def list_order_events(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: created_at"),
    ] = None,
) -> _pagination.Page[OrderEventRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await OrderEventRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[OrderEventRead](
        items=[OrderEventRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=OrderEventRead)
async def get_order_events(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> OrderEventRead:
    item = await OrderEventRepository(session, **access.repo_kwargs).get(item_id)
    return OrderEventRead.model_validate(item)


@router.post("", response_model=OrderEventRead, status_code=201)
async def create_order_events(
    body: OrderEventCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> OrderEventRead:
    item = await OrderEventRepository(session, **access.repo_kwargs).create(body.model_dump())
    return OrderEventRead.model_validate(item)
