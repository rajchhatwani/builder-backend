"""HTTP routes for Cart (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.carts import CartRepository
from app.schemas.carts import CartCreate, CartRead, CartUpdate

router = _fa.APIRouter(prefix="/carts", tags=["carts"])

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


@router.get("", response_model=_pagination.Page[CartRead])
async def list_carts(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: created_at, updated_at"),
    ] = None,
    f_status: _t.Annotated[str | None, _fa.Query(alias="status")] = None,
    f_token: _t.Annotated[str | None, _fa.Query(alias="token")] = None,
) -> _pagination.Page[CartRead]:
    filters: dict[str, _t.Any] = {
        "status": f_status,
        "token": f_token,
    }
    items, total = await CartRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[CartRead](
        items=[CartRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=CartRead)
async def get_carts(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> CartRead:
    item = await CartRepository(session, **access.repo_kwargs).get(item_id)
    return CartRead.model_validate(item)


@router.head("/{item_id}")
async def head_carts(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await CartRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Cart not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=CartRead, status_code=201)
async def create_carts(
    body: CartCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> CartRead:
    item = await CartRepository(session, **access.repo_kwargs).create(body.model_dump())
    return CartRead.model_validate(item)


@router.put("/{item_id}", response_model=CartRead)
async def replace_carts(
    item_id: _uuid.UUID, body: CartCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> CartRead:
    item = await CartRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return CartRead.model_validate(item)


@router.patch("/{item_id}", response_model=CartRead)
async def update_carts(
    item_id: _uuid.UUID, body: CartUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> CartRead:
    item = await CartRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return CartRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_carts(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await CartRepository(session, **access.repo_kwargs).delete(item_id)
