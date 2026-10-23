"""HTTP routes for Discount (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.discounts import DiscountRepository
from app.schemas.discounts import DiscountCreate, DiscountRead, DiscountUpdate

router = _fa.APIRouter(prefix="/discounts", tags=["discounts"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("manager", "marketing"), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("manager", "marketing"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("manager", "marketing"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[DiscountRead])
async def list_discounts(
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
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: code, title")
    ] = None,
    f_active: _t.Annotated[bool | None, _fa.Query(alias="active")] = None,
    f_code: _t.Annotated[str | None, _fa.Query(alias="code")] = None,
    f_kind: _t.Annotated[str | None, _fa.Query(alias="kind")] = None,
) -> _pagination.Page[DiscountRead]:
    filters: dict[str, _t.Any] = {
        "active": f_active,
        "code": f_code,
        "kind": f_kind,
    }
    items, total = await DiscountRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[DiscountRead](
        items=[DiscountRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=DiscountRead)
async def get_discounts(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> DiscountRead:
    item = await DiscountRepository(session, **access.repo_kwargs).get(item_id)
    return DiscountRead.model_validate(item)


@router.head("/{item_id}")
async def head_discounts(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await DiscountRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Discount not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=DiscountRead, status_code=201)
async def create_discounts(
    body: DiscountCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> DiscountRead:
    item = await DiscountRepository(session, **access.repo_kwargs).create(body.model_dump())
    return DiscountRead.model_validate(item)


@router.put("/{item_id}", response_model=DiscountRead)
async def replace_discounts(
    item_id: _uuid.UUID, body: DiscountCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> DiscountRead:
    item = await DiscountRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return DiscountRead.model_validate(item)


@router.patch("/{item_id}", response_model=DiscountRead)
async def update_discounts(
    item_id: _uuid.UUID, body: DiscountUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> DiscountRead:
    item = await DiscountRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return DiscountRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_discounts(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await DiscountRepository(session, **access.repo_kwargs).delete(item_id)
