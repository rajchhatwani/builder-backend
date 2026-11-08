"""HTTP routes for Employee (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.employees import EmployeeRepository
from app.schemas.employees import EmployeeCreate, EmployeeRead, EmployeeUpdate

router = _fa.APIRouter(prefix="/employees", tags=["employees"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("hr",)),
    "delete": _access.access_dependency(roles=("hr",)),
    "get": _access.access_dependency(roles=("employee", "hr", "manager")),
    "list": _access.access_dependency(roles=("employee", "hr", "manager")),
    "update": _access.access_dependency(roles=("hr",)),
}


@router.get("", response_model=_pagination.Page[EmployeeRead])
async def list_employees(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: name"),
    ] = None,
    f_department: _t.Annotated[str | None, _fa.Query(alias="department")] = None,
) -> _pagination.Page[EmployeeRead]:
    filters: dict[str, _t.Any] = {
        "department": f_department,
    }
    items, total = await EmployeeRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[EmployeeRead](
        items=[EmployeeRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=EmployeeRead)
async def get_employees(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> EmployeeRead:
    item = await EmployeeRepository(session, **access.repo_kwargs).get(item_id)
    return EmployeeRead.model_validate(item)


@router.head("/{item_id}")
async def head_employees(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await EmployeeRepository(session).exists(item_id):
        raise _errors.NotFoundError("Employee not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=EmployeeRead, status_code=201)
async def create_employees(
    body: EmployeeCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> EmployeeRead:
    item = await EmployeeRepository(session, **access.repo_kwargs).create(body.model_dump())
    return EmployeeRead.model_validate(item)


@router.put("/{item_id}", response_model=EmployeeRead)
async def replace_employees(
    item_id: _uuid.UUID, body: EmployeeCreate, session: _db.SessionDep
) -> EmployeeRead:
    item = await EmployeeRepository(session).replace(item_id, body.model_dump())
    return EmployeeRead.model_validate(item)


@router.patch("/{item_id}", response_model=EmployeeRead)
async def update_employees(
    item_id: _uuid.UUID, body: EmployeeUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> EmployeeRead:
    item = await EmployeeRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return EmployeeRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_employees(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await EmployeeRepository(session, **access.repo_kwargs).delete(item_id)
