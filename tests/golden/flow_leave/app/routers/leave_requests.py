"""HTTP routes for LeaveRequest (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.leave_requests import LeaveRequestRepository
from app.schemas.leave_requests import LeaveRequestCreate, LeaveRequestRead, LeaveRequestUpdate

router = _fa.APIRouter(prefix="/leave_requests", tags=["leave_requests"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("employee", "hr")),
    "delete": _access.access_dependency(roles=("hr",)),
    "get": _access.access_dependency(roles=("employee", "hr", "manager")),
    "list": _access.access_dependency(roles=("employee", "hr", "manager")),
}


@router.get("", response_model=_pagination.Page[LeaveRequestRead])
async def list_leave_requests(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: created_at"),
    ] = None,
    f_state: _t.Annotated[str | None, _fa.Query(alias="state")] = None,
) -> _pagination.Page[LeaveRequestRead]:
    filters: dict[str, _t.Any] = {
        "state": f_state,
    }
    items, total = await LeaveRequestRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[LeaveRequestRead](
        items=[LeaveRequestRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=LeaveRequestRead)
async def get_leave_requests(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> LeaveRequestRead:
    item = await LeaveRequestRepository(session, **access.repo_kwargs).get(item_id)
    return LeaveRequestRead.model_validate(item)


@router.head("/{item_id}")
async def head_leave_requests(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await LeaveRequestRepository(session).exists(item_id):
        raise _errors.NotFoundError("LeaveRequest not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=LeaveRequestRead, status_code=201)
async def create_leave_requests(
    body: LeaveRequestCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> LeaveRequestRead:
    item = await LeaveRequestRepository(session, **access.repo_kwargs).create(body.model_dump())
    return LeaveRequestRead.model_validate(item)


@router.put("/{item_id}", response_model=LeaveRequestRead)
async def replace_leave_requests(
    item_id: _uuid.UUID, body: LeaveRequestCreate, session: _db.SessionDep
) -> LeaveRequestRead:
    item = await LeaveRequestRepository(session).replace(item_id, body.model_dump())
    return LeaveRequestRead.model_validate(item)


@router.patch("/{item_id}", response_model=LeaveRequestRead)
async def update_leave_requests(
    item_id: _uuid.UUID, body: LeaveRequestUpdate, session: _db.SessionDep
) -> LeaveRequestRead:
    item = await LeaveRequestRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return LeaveRequestRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_leave_requests(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await LeaveRequestRepository(session, **access.repo_kwargs).delete(item_id)
