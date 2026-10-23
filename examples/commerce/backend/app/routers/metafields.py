"""HTTP routes for Metafield (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.metafields import MetafieldRepository
from app.schemas.metafields import MetafieldCreate, MetafieldRead, MetafieldUpdate

router = _fa.APIRouter(prefix="/metafields", tags=["metafields"])

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


@router.get("", response_model=_pagination.Page[MetafieldRead])
async def list_metafields(
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
    f_key: _t.Annotated[str | None, _fa.Query(alias="key")] = None,
    f_namespace: _t.Annotated[str | None, _fa.Query(alias="namespace")] = None,
    f_owner_id: _t.Annotated[_uuid.UUID | None, _fa.Query(alias="owner_id")] = None,
    f_owner_type: _t.Annotated[str | None, _fa.Query(alias="owner_type")] = None,
) -> _pagination.Page[MetafieldRead]:
    filters: dict[str, _t.Any] = {
        "key": f_key,
        "namespace": f_namespace,
        "owner_id": f_owner_id,
        "owner_type": f_owner_type,
    }
    items, total = await MetafieldRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[MetafieldRead](
        items=[MetafieldRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=MetafieldRead)
async def get_metafields(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> MetafieldRead:
    item = await MetafieldRepository(session, **access.repo_kwargs).get(item_id)
    return MetafieldRead.model_validate(item)


@router.head("/{item_id}")
async def head_metafields(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await MetafieldRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Metafield not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=MetafieldRead, status_code=201)
async def create_metafields(
    body: MetafieldCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> MetafieldRead:
    item = await MetafieldRepository(session, **access.repo_kwargs).create(body.model_dump())
    return MetafieldRead.model_validate(item)


@router.put("/{item_id}", response_model=MetafieldRead)
async def replace_metafields(
    item_id: _uuid.UUID, body: MetafieldCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> MetafieldRead:
    item = await MetafieldRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return MetafieldRead.model_validate(item)


@router.patch("/{item_id}", response_model=MetafieldRead)
async def update_metafields(
    item_id: _uuid.UUID, body: MetafieldUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> MetafieldRead:
    item = await MetafieldRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return MetafieldRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_metafields(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await MetafieldRepository(session, **access.repo_kwargs).delete(item_id)
