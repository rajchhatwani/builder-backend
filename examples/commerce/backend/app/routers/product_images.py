"""HTTP routes for ProductImage (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.product_images import ProductImageRepository
from app.schemas.product_images import ProductImageCreate, ProductImageRead, ProductImageUpdate

router = _fa.APIRouter(prefix="/product_images", tags=["product_images"])

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


@router.get("", response_model=_pagination.Page[ProductImageRead])
async def list_product_images(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: position"),
    ] = None,
) -> _pagination.Page[ProductImageRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await ProductImageRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[ProductImageRead](
        items=[ProductImageRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ProductImageRead)
async def get_product_images(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> ProductImageRead:
    item = await ProductImageRepository(session, **access.repo_kwargs).get(item_id)
    return ProductImageRead.model_validate(item)


@router.head("/{item_id}")
async def head_product_images(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await ProductImageRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("ProductImage not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=ProductImageRead, status_code=201)
async def create_product_images(
    body: ProductImageCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> ProductImageRead:
    item = await ProductImageRepository(session, **access.repo_kwargs).create(body.model_dump())
    return ProductImageRead.model_validate(item)


@router.put("/{item_id}", response_model=ProductImageRead)
async def replace_product_images(
    item_id: _uuid.UUID, body: ProductImageCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> ProductImageRead:
    item = await ProductImageRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return ProductImageRead.model_validate(item)


@router.patch("/{item_id}", response_model=ProductImageRead)
async def update_product_images(
    item_id: _uuid.UUID, body: ProductImageUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> ProductImageRead:
    item = await ProductImageRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return ProductImageRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_product_images(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await ProductImageRepository(session, **access.repo_kwargs).delete(item_id)
