"""HTTP routes for Patient (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.patients import PatientRepository
from app.schemas.patients import PatientCreate, PatientRead, PatientUpdate

router = _fa.APIRouter(prefix="/patients", tags=["patients"])

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


@router.get("", response_model=_pagination.Page[PatientRead])
async def list_patients(
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
    f_postcode: _t.Annotated[str | None, _fa.Query(alias="postcode")] = None,
) -> _pagination.Page[PatientRead]:
    filters: dict[str, _t.Any] = {
        "postcode": f_postcode,
    }
    items, total = await PatientRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[PatientRead](
        items=[PatientRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=PatientRead)
async def get_patients(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> PatientRead:
    item = await PatientRepository(session, **access.repo_kwargs).get(item_id)
    return PatientRead.model_validate(item)


@router.head("/{item_id}")
async def head_patients(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await PatientRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Patient not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=PatientRead, status_code=201)
async def create_patients(
    body: PatientCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> PatientRead:
    item = await PatientRepository(session, **access.repo_kwargs).create(body.model_dump())
    return PatientRead.model_validate(item)


@router.put("/{item_id}", response_model=PatientRead)
async def replace_patients(
    item_id: _uuid.UUID, body: PatientCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> PatientRead:
    item = await PatientRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return PatientRead.model_validate(item)


@router.patch("/{item_id}", response_model=PatientRead)
async def update_patients(
    item_id: _uuid.UUID, body: PatientUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> PatientRead:
    item = await PatientRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return PatientRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_patients(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await PatientRepository(session, **access.repo_kwargs).delete(item_id)
