"""HTTP routes for Appointment (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.appointments import AppointmentRepository
from app.schemas.appointments import AppointmentCreate, AppointmentRead, AppointmentUpdate

router = _fa.APIRouter(prefix="/appointments", tags=["appointments"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin", "clinician_lead", "compliance_officer", "member"), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("admin", "clinician_lead", "compliance_officer", "member"), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("admin", "clinician_lead", "compliance_officer", "member"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("admin", "clinician_lead", "compliance_officer", "member"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("admin", "clinician_lead", "compliance_officer", "member"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("admin", "clinician_lead", "compliance_officer", "member"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("admin", "clinician_lead", "compliance_officer", "member"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[AppointmentRead])
async def list_appointments(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: scheduled_at"),
    ] = None,
    f_status: _t.Annotated[str | None, _fa.Query(alias="status")] = None,
) -> _pagination.Page[AppointmentRead]:
    filters: dict[str, _t.Any] = {
        "status": f_status,
    }
    items, total = await AppointmentRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[AppointmentRead](
        items=[AppointmentRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=AppointmentRead)
async def get_appointments(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> AppointmentRead:
    item = await AppointmentRepository(session, **access.repo_kwargs).get(item_id)
    return AppointmentRead.model_validate(item)


@router.head("/{item_id}")
async def head_appointments(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await AppointmentRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Appointment not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=AppointmentRead, status_code=201)
async def create_appointments(
    body: AppointmentCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> AppointmentRead:
    item = await AppointmentRepository(session, **access.repo_kwargs).create(body.model_dump())
    return AppointmentRead.model_validate(item)


@router.put("/{item_id}", response_model=AppointmentRead)
async def replace_appointments(
    item_id: _uuid.UUID, body: AppointmentCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> AppointmentRead:
    item = await AppointmentRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return AppointmentRead.model_validate(item)


@router.patch("/{item_id}", response_model=AppointmentRead)
async def update_appointments(
    item_id: _uuid.UUID, body: AppointmentUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> AppointmentRead:
    item = await AppointmentRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return AppointmentRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_appointments(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await AppointmentRepository(session, **access.repo_kwargs).delete(item_id)
