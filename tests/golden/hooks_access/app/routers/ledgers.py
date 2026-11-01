"""HTTP routes for Ledger (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.ledgers import LedgerRepository
from app.schemas.ledgers import LedgerCreate, LedgerRead, LedgerUpdate

router = _fa.APIRouter(prefix="/ledgers", tags=["ledgers"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin",), authenticate=True, tenant=True),
    "delete": _access.access_dependency(authenticate=True, tenant=True),
    "get": _access.access_dependency(authenticate=True, tenant=True),
    "head": _access.access_dependency(authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("admin",), authenticate=True, tenant=True),
    "replace": _access.access_dependency(authenticate=True, tenant=True),
    "update": _access.access_dependency(authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[LedgerRead])
async def list_ledgers(
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
) -> _pagination.Page[LedgerRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await LedgerRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[LedgerRead](
        items=[LedgerRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=LedgerRead)
async def get_ledgers(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> LedgerRead:
    item = await LedgerRepository(session, **access.repo_kwargs).get(item_id)
    return LedgerRead.model_validate(item)


@router.head("/{item_id}")
async def head_ledgers(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await LedgerRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Ledger not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=LedgerRead, status_code=201)
async def create_ledgers(
    body: LedgerCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> LedgerRead:
    item = await LedgerRepository(session, **access.repo_kwargs).create(body.model_dump())
    return LedgerRead.model_validate(item)


@router.put("/{item_id}", response_model=LedgerRead)
async def replace_ledgers(
    item_id: _uuid.UUID, body: LedgerCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> LedgerRead:
    item = await LedgerRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return LedgerRead.model_validate(item)


@router.patch("/{item_id}", response_model=LedgerRead)
async def update_ledgers(
    item_id: _uuid.UUID, body: LedgerUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> LedgerRead:
    item = await LedgerRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return LedgerRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_ledgers(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await LedgerRepository(session, **access.repo_kwargs).delete(item_id)
