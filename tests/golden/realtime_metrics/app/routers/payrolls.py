"""HTTP routes for Payroll (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.payrolls import PayrollRepository
from app.schemas.payrolls import PayrollCreate, PayrollRead, PayrollUpdate

router = _fa.APIRouter(prefix="/payrolls", tags=["payrolls"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin",)),
    "delete": _access.access_dependency(roles=("admin",)),
    "get": _access.access_dependency(roles=("admin",)),
    "list": _access.access_dependency(roles=("admin",)),
    "update": _access.access_dependency(roles=("admin",)),
}


@router.get("", response_model=_pagination.Page[PayrollRead])
async def list_payrolls(
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
) -> _pagination.Page[PayrollRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await PayrollRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[PayrollRead](
        items=[PayrollRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=PayrollRead)
async def get_payrolls(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> PayrollRead:
    item = await PayrollRepository(session, **access.repo_kwargs).get(item_id)
    return PayrollRead.model_validate(item)


@router.head("/{item_id}")
async def head_payrolls(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await PayrollRepository(session).exists(item_id):
        raise _errors.NotFoundError("Payroll not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=PayrollRead, status_code=201)
async def create_payrolls(
    body: PayrollCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> PayrollRead:
    item = await PayrollRepository(session, **access.repo_kwargs).create(body.model_dump())
    return PayrollRead.model_validate(item)


@router.put("/{item_id}", response_model=PayrollRead)
async def replace_payrolls(
    item_id: _uuid.UUID, body: PayrollCreate, session: _db.SessionDep
) -> PayrollRead:
    item = await PayrollRepository(session).replace(item_id, body.model_dump())
    return PayrollRead.model_validate(item)


@router.patch("/{item_id}", response_model=PayrollRead)
async def update_payrolls(
    item_id: _uuid.UUID, body: PayrollUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> PayrollRead:
    item = await PayrollRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return PayrollRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_payrolls(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await PayrollRepository(session, **access.repo_kwargs).delete(item_id)
