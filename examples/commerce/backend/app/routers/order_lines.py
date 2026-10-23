"""HTTP routes for OrderLine (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import pagination as _pagination
from app.crud.order_lines import OrderLineRepository
from app.schemas.order_lines import OrderLineCreate, OrderLineRead, OrderLineUpdate

router = _fa.APIRouter(prefix="/order_lines", tags=["order_lines"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("fulfillment", "manager", "support"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[OrderLineRead])
async def list_order_lines(
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
) -> _pagination.Page[OrderLineRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await OrderLineRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[OrderLineRead](
        items=[OrderLineRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=OrderLineRead)
async def get_order_lines(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> OrderLineRead:
    item = await OrderLineRepository(session, **access.repo_kwargs).get(item_id)
    return OrderLineRead.model_validate(item)


@router.post("", response_model=OrderLineRead, status_code=201)
async def create_order_lines(
    body: OrderLineCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> OrderLineRead:
    item = await OrderLineRepository(session, **access.repo_kwargs).create(body.model_dump())
    return OrderLineRead.model_validate(item)


@router.patch("/{item_id}", response_model=OrderLineRead)
async def update_order_lines(
    item_id: _uuid.UUID, body: OrderLineUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> OrderLineRead:
    item = await OrderLineRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return OrderLineRead.model_validate(item)
