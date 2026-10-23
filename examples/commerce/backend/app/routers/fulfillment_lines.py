"""HTTP routes for FulfillmentLine (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.fulfillment_lines import FulfillmentLineRepository
from app.schemas.fulfillment_lines import FulfillmentLineCreate, FulfillmentLineRead, FulfillmentLineUpdate

router = _fa.APIRouter(prefix="/fulfillment_lines", tags=["fulfillment_lines"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("fulfillment", "manager"), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("fulfillment", "manager", "support"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("fulfillment", "manager", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("fulfillment", "manager", "support"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("fulfillment", "manager"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("fulfillment", "manager"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[FulfillmentLineRead])
async def list_fulfillment_lines(
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
) -> _pagination.Page[FulfillmentLineRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await FulfillmentLineRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[FulfillmentLineRead](
        items=[FulfillmentLineRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=FulfillmentLineRead)
async def get_fulfillment_lines(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> FulfillmentLineRead:
    item = await FulfillmentLineRepository(session, **access.repo_kwargs).get(item_id)
    return FulfillmentLineRead.model_validate(item)


@router.head("/{item_id}")
async def head_fulfillment_lines(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await FulfillmentLineRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("FulfillmentLine not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=FulfillmentLineRead, status_code=201)
async def create_fulfillment_lines(
    body: FulfillmentLineCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> FulfillmentLineRead:
    item = await FulfillmentLineRepository(session, **access.repo_kwargs).create(body.model_dump())
    return FulfillmentLineRead.model_validate(item)


@router.put("/{item_id}", response_model=FulfillmentLineRead)
async def replace_fulfillment_lines(
    item_id: _uuid.UUID, body: FulfillmentLineCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> FulfillmentLineRead:
    item = await FulfillmentLineRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return FulfillmentLineRead.model_validate(item)


@router.patch("/{item_id}", response_model=FulfillmentLineRead)
async def update_fulfillment_lines(
    item_id: _uuid.UUID, body: FulfillmentLineUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> FulfillmentLineRead:
    item = await FulfillmentLineRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return FulfillmentLineRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_fulfillment_lines(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await FulfillmentLineRepository(session, **access.repo_kwargs).delete(item_id)
