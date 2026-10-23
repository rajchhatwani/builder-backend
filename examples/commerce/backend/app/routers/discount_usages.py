"""HTTP routes for DiscountUsage (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import pagination as _pagination
from app.crud.discount_usages import DiscountUsageRepository
from app.schemas.discount_usages import DiscountUsageCreate, DiscountUsageRead

router = _fa.APIRouter(prefix="/discount_usages", tags=["discount_usages"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("manager", "marketing"), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[DiscountUsageRead])
async def list_discount_usages(
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
) -> _pagination.Page[DiscountUsageRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await DiscountUsageRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[DiscountUsageRead](
        items=[DiscountUsageRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=DiscountUsageRead)
async def get_discount_usages(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> DiscountUsageRead:
    item = await DiscountUsageRepository(session, **access.repo_kwargs).get(item_id)
    return DiscountUsageRead.model_validate(item)


@router.post("", response_model=DiscountUsageRead, status_code=201)
async def create_discount_usages(
    body: DiscountUsageCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> DiscountUsageRead:
    item = await DiscountUsageRepository(session, **access.repo_kwargs).create(body.model_dump())
    return DiscountUsageRead.model_validate(item)
