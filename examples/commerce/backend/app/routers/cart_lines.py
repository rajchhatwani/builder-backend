"""HTTP routes for CartLine (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.cart_lines import CartLineRepository
from app.schemas.cart_lines import CartLineCreate, CartLineRead, CartLineUpdate

router = _fa.APIRouter(prefix="/cart_lines", tags=["cart_lines"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("manager", "support"), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("manager", "marketing", "support"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("manager", "marketing", "support"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("manager", "support"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("manager", "support"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[CartLineRead])
async def list_cart_lines(
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
) -> _pagination.Page[CartLineRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await CartLineRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[CartLineRead](
        items=[CartLineRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=CartLineRead)
async def get_cart_lines(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> CartLineRead:
    item = await CartLineRepository(session, **access.repo_kwargs).get(item_id)
    return CartLineRead.model_validate(item)


@router.head("/{item_id}")
async def head_cart_lines(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await CartLineRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("CartLine not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=CartLineRead, status_code=201)
async def create_cart_lines(
    body: CartLineCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> CartLineRead:
    item = await CartLineRepository(session, **access.repo_kwargs).create(body.model_dump())
    return CartLineRead.model_validate(item)


@router.put("/{item_id}", response_model=CartLineRead)
async def replace_cart_lines(
    item_id: _uuid.UUID, body: CartLineCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> CartLineRead:
    item = await CartLineRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return CartLineRead.model_validate(item)


@router.patch("/{item_id}", response_model=CartLineRead)
async def update_cart_lines(
    item_id: _uuid.UUID, body: CartLineUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> CartLineRead:
    item = await CartLineRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return CartLineRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_cart_lines(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await CartLineRepository(session, **access.repo_kwargs).delete(item_id)
