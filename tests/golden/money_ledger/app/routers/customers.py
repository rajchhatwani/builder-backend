"""HTTP routes for Customer (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import pagination as _pagination
from app.crud.customers import CustomerRepository
from app.schemas.customers import CustomerCreate, CustomerRead

router = _fa.APIRouter(prefix="/customers", tags=["customers"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin", "member"), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("admin", "member"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("admin", "member"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[CustomerRead])
async def list_customers(
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
) -> _pagination.Page[CustomerRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await CustomerRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[CustomerRead](
        items=[CustomerRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=CustomerRead)
async def get_customers(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> CustomerRead:
    item = await CustomerRepository(session, **access.repo_kwargs).get(item_id)
    return CustomerRead.model_validate(item)


@router.post("", response_model=CustomerRead, status_code=201)
async def create_customers(
    body: CustomerCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> CustomerRead:
    item = await CustomerRepository(session, **access.repo_kwargs).create(body.model_dump())
    return CustomerRead.model_validate(item)
