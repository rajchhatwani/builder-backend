"""HTTP routes for Report (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.reports import ReportRepository
from app.schemas.reports import ReportCreate, ReportRead, ReportUpdate

router = _fa.APIRouter(prefix="/reports", tags=["reports"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin",)),
    "list": _access.access_dependency(roles=("admin",)),
}


@router.get("", response_model=_pagination.Page[ReportRead])
async def list_reports(
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
) -> _pagination.Page[ReportRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await ReportRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[ReportRead](
        items=[ReportRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ReportRead)
async def get_reports(item_id: _uuid.UUID, session: _db.SessionDep) -> ReportRead:
    item = await ReportRepository(session).get(item_id)
    return ReportRead.model_validate(item)


@router.head("/{item_id}")
async def head_reports(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await ReportRepository(session).exists(item_id):
        raise _errors.NotFoundError("Report not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=ReportRead, status_code=201)
async def create_reports(
    body: ReportCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> ReportRead:
    item = await ReportRepository(session, **access.repo_kwargs).create(body.model_dump())
    return ReportRead.model_validate(item)


@router.put("/{item_id}", response_model=ReportRead)
async def replace_reports(
    item_id: _uuid.UUID, body: ReportCreate, session: _db.SessionDep
) -> ReportRead:
    item = await ReportRepository(session).replace(item_id, body.model_dump())
    return ReportRead.model_validate(item)


@router.patch("/{item_id}", response_model=ReportRead)
async def update_reports(
    item_id: _uuid.UUID, body: ReportUpdate, session: _db.SessionDep
) -> ReportRead:
    item = await ReportRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return ReportRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_reports(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await ReportRepository(session).delete(item_id)
