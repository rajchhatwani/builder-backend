"""HTTP routes for Comment (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.auth import authorize as _authz
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.comments import CommentRepository
from app.schemas.comments import CommentCreate, CommentRead, CommentUpdate

router = _fa.APIRouter(prefix="/comments", tags=["comments"])

# Who may call each operation, and which rows they get (see app/auth/access.py and app/auth/authorize.py).
_ACCESS = {
    "create": _authz.policy_dependency('Comment', 'create', stamp=True),
    "delete": _authz.policy_dependency('Comment', 'delete'),
    "get": _authz.policy_dependency('Comment', 'get'),
    "head": _authz.policy_dependency('Comment', 'head'),
    "list": _authz.policy_dependency('Comment', 'list'),
    "replace": _authz.policy_dependency('Comment', 'replace'),
    "update": _authz.policy_dependency('Comment', 'update'),
}


@router.get("", response_model=_pagination.Page[CommentRead])
async def list_comments(
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
) -> _pagination.Page[CommentRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await CommentRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[CommentRead](
        items=[CommentRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=CommentRead)
async def get_comments(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> CommentRead:
    item = await CommentRepository(session, **access.repo_kwargs).get(item_id)
    return CommentRead.model_validate(item)


@router.head("/{item_id}")
async def head_comments(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await CommentRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Comment not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=CommentRead, status_code=201)
async def create_comments(
    body: CommentCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> CommentRead:
    item = await CommentRepository(session, **access.repo_kwargs).create(body.model_dump())
    return CommentRead.model_validate(item)


@router.put("/{item_id}", response_model=CommentRead)
async def replace_comments(
    item_id: _uuid.UUID, body: CommentCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> CommentRead:
    item = await CommentRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return CommentRead.model_validate(item)


@router.patch("/{item_id}", response_model=CommentRead)
async def update_comments(
    item_id: _uuid.UUID, body: CommentUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> CommentRead:
    item = await CommentRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return CommentRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_comments(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await CommentRepository(session, **access.repo_kwargs).delete(item_id)
