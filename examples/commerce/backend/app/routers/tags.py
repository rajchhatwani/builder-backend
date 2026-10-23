"""HTTP routes for Tag (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.tags import TagRepository
from app.schemas.tags import TagCreate, TagRead, TagUpdate

router = _fa.APIRouter(prefix="/tags", tags=["tags"])

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


@router.get("", response_model=_pagination.Page[TagRead])
async def list_tags(
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
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: name")
    ] = None,
) -> _pagination.Page[TagRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await TagRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[TagRead](
        items=[TagRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=TagRead)
async def get_tags(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> TagRead:
    item = await TagRepository(session, **access.repo_kwargs).get(item_id)
    return TagRead.model_validate(item)


@router.head("/{item_id}")
async def head_tags(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await TagRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Tag not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=TagRead, status_code=201)
async def create_tags(
    body: TagCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> TagRead:
    item = await TagRepository(session, **access.repo_kwargs).create(body.model_dump())
    return TagRead.model_validate(item)


@router.put("/{item_id}", response_model=TagRead)
async def replace_tags(
    item_id: _uuid.UUID, body: TagCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> TagRead:
    item = await TagRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return TagRead.model_validate(item)


@router.patch("/{item_id}", response_model=TagRead)
async def update_tags(
    item_id: _uuid.UUID, body: TagUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> TagRead:
    item = await TagRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return TagRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_tags(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await TagRepository(session, **access.repo_kwargs).delete(item_id)
