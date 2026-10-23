"""HTTP routes for Deal (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.deals import DealRepository
from app.schemas.deals import DealCreate, DealRead, DealUpdate

router = _fa.APIRouter(prefix="/deals", tags=["deals"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin", "member"), stamp=True, authenticate=True, tenant=True),
    "delete": _access.access_dependency(authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("admin", "member"), owner=True, authenticate=True, tenant=True),
    "head": _access.access_dependency(authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("admin", "member"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(authenticate=True, tenant=True),
    "update": _access.access_dependency(authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[DealRead])
async def list_deals(
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
) -> _pagination.Page[DealRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await DealRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[DealRead](
        items=[DealRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=DealRead)
async def get_deals(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> DealRead:
    item = await DealRepository(session, **access.repo_kwargs).get(item_id)
    return DealRead.model_validate(item)


@router.head("/{item_id}")
async def head_deals(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await DealRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Deal not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=DealRead, status_code=201)
async def create_deals(
    body: DealCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> DealRead:
    item = await DealRepository(session, **access.repo_kwargs).create(body.model_dump())
    return DealRead.model_validate(item)


@router.put("/{item_id}", response_model=DealRead)
async def replace_deals(
    item_id: _uuid.UUID, body: DealCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> DealRead:
    item = await DealRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return DealRead.model_validate(item)


@router.patch("/{item_id}", response_model=DealRead)
async def update_deals(
    item_id: _uuid.UUID, body: DealUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> DealRead:
    item = await DealRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return DealRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_deals(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await DealRepository(session, **access.repo_kwargs).delete(item_id)
