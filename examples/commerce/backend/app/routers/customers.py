"""HTTP routes for Customer (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.customers import CustomerRepository
from app.schemas.customers import CustomerCreate, CustomerRead, CustomerUpdate

router = _fa.APIRouter(prefix="/customers", tags=["customers"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("manager", "support"), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("manager", "marketing", "support"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("manager", "marketing", "support"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("manager", "support"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("manager", "support"), authenticate=True, tenant=True),
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
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: created_at, orders_count, total_spent"),
    ] = None,
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: email, first_name, last_name, phone")
    ] = None,
    f_accepts_marketing: _t.Annotated[bool | None, _fa.Query(alias="accepts_marketing")] = None,
    f_email: _t.Annotated[str | None, _fa.Query(alias="email")] = None,
    f_state: _t.Annotated[str | None, _fa.Query(alias="state")] = None,
) -> _pagination.Page[CustomerRead]:
    filters: dict[str, _t.Any] = {
        "accepts_marketing": f_accepts_marketing,
        "email": f_email,
        "state": f_state,
    }
    items, total = await CustomerRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
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


@router.head("/{item_id}")
async def head_customers(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await CustomerRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Customer not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=CustomerRead, status_code=201)
async def create_customers(
    body: CustomerCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> CustomerRead:
    item = await CustomerRepository(session, **access.repo_kwargs).create(body.model_dump())
    return CustomerRead.model_validate(item)


@router.put("/{item_id}", response_model=CustomerRead)
async def replace_customers(
    item_id: _uuid.UUID, body: CustomerCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> CustomerRead:
    item = await CustomerRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return CustomerRead.model_validate(item)


@router.patch("/{item_id}", response_model=CustomerRead)
async def update_customers(
    item_id: _uuid.UUID, body: CustomerUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> CustomerRead:
    item = await CustomerRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return CustomerRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_customers(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await CustomerRepository(session, **access.repo_kwargs).delete(item_id)
