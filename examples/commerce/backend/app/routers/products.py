"""HTTP routes for Product (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.products import ProductRepository
from app.schemas.products import ProductCreate, ProductRead, ProductUpdate

router = _fa.APIRouter(prefix="/products", tags=["products"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("catalog", "manager"), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("catalog", "manager"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("catalog", "manager"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[ProductRead])
async def list_products(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: created_at, published_at, title, updated_at"),
    ] = None,
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: handle, title, vendor")
    ] = None,
    f_handle: _t.Annotated[str | None, _fa.Query(alias="handle")] = None,
    f_product_type: _t.Annotated[str | None, _fa.Query(alias="product_type")] = None,
    f_status: _t.Annotated[str | None, _fa.Query(alias="status")] = None,
    f_vendor: _t.Annotated[str | None, _fa.Query(alias="vendor")] = None,
) -> _pagination.Page[ProductRead]:
    filters: dict[str, _t.Any] = {
        "handle": f_handle,
        "product_type": f_product_type,
        "status": f_status,
        "vendor": f_vendor,
    }
    items, total = await ProductRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[ProductRead](
        items=[ProductRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ProductRead)
async def get_products(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> ProductRead:
    item = await ProductRepository(session, **access.repo_kwargs).get(item_id)
    return ProductRead.model_validate(item)


@router.head("/{item_id}")
async def head_products(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await ProductRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Product not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=ProductRead, status_code=201)
async def create_products(
    body: ProductCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> ProductRead:
    item = await ProductRepository(session, **access.repo_kwargs).create(body.model_dump())
    return ProductRead.model_validate(item)


@router.put("/{item_id}", response_model=ProductRead)
async def replace_products(
    item_id: _uuid.UUID, body: ProductCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> ProductRead:
    item = await ProductRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return ProductRead.model_validate(item)


@router.patch("/{item_id}", response_model=ProductRead)
async def update_products(
    item_id: _uuid.UUID, body: ProductUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> ProductRead:
    item = await ProductRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return ProductRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_products(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await ProductRepository(session, **access.repo_kwargs).delete(item_id)
