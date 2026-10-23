"""HTTP routes for Variant (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.variants import VariantRepository
from app.schemas.variants import VariantCreate, VariantRead, VariantUpdate

router = _fa.APIRouter(prefix="/variants", tags=["variants"])

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


@router.get("", response_model=_pagination.Page[VariantRead])
async def list_variants(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: created_at, position, price"),
    ] = None,
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: barcode, sku, title")
    ] = None,
    f_barcode: _t.Annotated[str | None, _fa.Query(alias="barcode")] = None,
    f_sku: _t.Annotated[str | None, _fa.Query(alias="sku")] = None,
) -> _pagination.Page[VariantRead]:
    filters: dict[str, _t.Any] = {
        "barcode": f_barcode,
        "sku": f_sku,
    }
    items, total = await VariantRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[VariantRead](
        items=[VariantRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=VariantRead)
async def get_variants(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> VariantRead:
    item = await VariantRepository(session, **access.repo_kwargs).get(item_id)
    return VariantRead.model_validate(item)


@router.head("/{item_id}")
async def head_variants(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await VariantRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Variant not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=VariantRead, status_code=201)
async def create_variants(
    body: VariantCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> VariantRead:
    item = await VariantRepository(session, **access.repo_kwargs).create(body.model_dump())
    return VariantRead.model_validate(item)


@router.put("/{item_id}", response_model=VariantRead)
async def replace_variants(
    item_id: _uuid.UUID, body: VariantCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> VariantRead:
    item = await VariantRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return VariantRead.model_validate(item)


@router.patch("/{item_id}", response_model=VariantRead)
async def update_variants(
    item_id: _uuid.UUID, body: VariantUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> VariantRead:
    item = await VariantRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return VariantRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_variants(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await VariantRepository(session, **access.repo_kwargs).delete(item_id)
