"""HTTP routes for Employee (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.auth import field_access as _fx
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.employees import EmployeeRepository
from app.schemas.employees import EmployeeCreate, EmployeeRead, EmployeeUpdate

router = _fa.APIRouter(prefix="/employees", tags=["employees"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("staff",), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("staff",), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("staff",), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("staff",), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("staff",), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("staff",), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("staff",), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[EmployeeRead], response_model_exclude_unset=True)
async def list_employees(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: name, salary"),
    ] = None,
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: name, notes")
    ] = None,
    f_name: _t.Annotated[str | None, _fa.Query(alias="name")] = None,
    f_salary: _t.Annotated[int | None, _fa.Query(alias="salary")] = None,
) -> _pagination.Page[EmployeeRead]:
    filters: dict[str, _t.Any] = {
        "name": f_name,
        "salary": f_salary,
    }
    items, total = await EmployeeRepository(session, **access.repo_kwargs, hidden_fields=_fx.hidden_read("Employee", access.user)).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[EmployeeRead](
        items=[_fx.shape("Employee", access.user, EmployeeRead.model_validate(item)) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=EmployeeRead, response_model_exclude_unset=True)
async def get_employees(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> EmployeeRead:
    item = await EmployeeRepository(session, **access.repo_kwargs).get(item_id)
    return _fx.shape("Employee", access.user, EmployeeRead.model_validate(item))


@router.head("/{item_id}")
async def head_employees(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await EmployeeRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Employee not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=EmployeeRead, status_code=201, response_model_exclude_unset=True)
async def create_employees(
    body: EmployeeCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> EmployeeRead:
    item = await EmployeeRepository(session, **access.repo_kwargs).create(_fx.payload("Employee", access.user, body, "create"))
    return _fx.shape("Employee", access.user, EmployeeRead.model_validate(item))


@router.put("/{item_id}", response_model=EmployeeRead, response_model_exclude_unset=True)
async def replace_employees(
    item_id: _uuid.UUID, body: EmployeeCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> EmployeeRead:
    item = await EmployeeRepository(session, **access.repo_kwargs).replace(item_id, _fx.payload("Employee", access.user, body, "replace"))
    return _fx.shape("Employee", access.user, EmployeeRead.model_validate(item))


@router.patch("/{item_id}", response_model=EmployeeRead, response_model_exclude_unset=True)
async def update_employees(
    item_id: _uuid.UUID, body: EmployeeUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> EmployeeRead:
    item = await EmployeeRepository(session, **access.repo_kwargs).update(item_id, _fx.payload("Employee", access.user, body, "update"))
    return _fx.shape("Employee", access.user, EmployeeRead.model_validate(item))


@router.delete("/{item_id}", status_code=204)
async def delete_employees(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await EmployeeRepository(session, **access.repo_kwargs).delete(item_id)
