"""HTTP routes for Collection (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.collections import CollectionRepository
from app.schemas.collections import CollectionCreate, CollectionRead, CollectionUpdate

router = _fa.APIRouter(prefix="/collections", tags=["collections"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("catalog", "manager"), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("catalog", "manager"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("catalog", "manager"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[CollectionRead])
async def list_collections(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: created_at, title"),
    ] = None,
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: handle, title")
    ] = None,
    f_handle: _t.Annotated[str | None, _fa.Query(alias="handle")] = None,
    f_kind: _t.Annotated[str | None, _fa.Query(alias="kind")] = None,
    f_published: _t.Annotated[bool | None, _fa.Query(alias="published")] = None,
) -> _pagination.Page[CollectionRead]:
    filters: dict[str, _t.Any] = {
        "handle": f_handle,
        "kind": f_kind,
        "published": f_published,
    }
    items, total = await CollectionRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[CollectionRead](
        items=[CollectionRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=CollectionRead)
async def get_collections(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> CollectionRead:
    item = await CollectionRepository(session, **access.repo_kwargs).get(item_id)
    return CollectionRead.model_validate(item)


@router.head("/{item_id}")
async def head_collections(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await CollectionRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Collection not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=CollectionRead, status_code=201)
async def create_collections(
    body: CollectionCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> CollectionRead:
    item = await CollectionRepository(session, **access.repo_kwargs).create(body.model_dump())
    return CollectionRead.model_validate(item)


@router.put("/{item_id}", response_model=CollectionRead)
async def replace_collections(
    item_id: _uuid.UUID, body: CollectionCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> CollectionRead:
    item = await CollectionRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return CollectionRead.model_validate(item)


@router.patch("/{item_id}", response_model=CollectionRead)
async def update_collections(
    item_id: _uuid.UUID, body: CollectionUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> CollectionRead:
    item = await CollectionRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return CollectionRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_collections(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await CollectionRepository(session, **access.repo_kwargs).delete(item_id)
