"""HTTP routes for Blog (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.blogs import BlogRepository
from app.schemas.blogs import BlogCreate, BlogRead, BlogUpdate

router = _fa.APIRouter(prefix="/blogs", tags=["blogs"])

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


@router.get("", response_model=_pagination.Page[BlogRead])
async def list_blogs(
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
) -> _pagination.Page[BlogRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await BlogRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[BlogRead](
        items=[BlogRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=BlogRead)
async def get_blogs(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> BlogRead:
    item = await BlogRepository(session, **access.repo_kwargs).get(item_id)
    return BlogRead.model_validate(item)


@router.head("/{item_id}")
async def head_blogs(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await BlogRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Blog not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=BlogRead, status_code=201)
async def create_blogs(
    body: BlogCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> BlogRead:
    item = await BlogRepository(session, **access.repo_kwargs).create(body.model_dump())
    return BlogRead.model_validate(item)


@router.put("/{item_id}", response_model=BlogRead)
async def replace_blogs(
    item_id: _uuid.UUID, body: BlogCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> BlogRead:
    item = await BlogRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return BlogRead.model_validate(item)


@router.patch("/{item_id}", response_model=BlogRead)
async def update_blogs(
    item_id: _uuid.UUID, body: BlogUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> BlogRead:
    item = await BlogRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return BlogRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_blogs(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await BlogRepository(session, **access.repo_kwargs).delete(item_id)
