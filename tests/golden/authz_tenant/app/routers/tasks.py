"""HTTP routes for Task (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.auth import authorize as _authz
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.tasks import TaskRepository
from app.schemas.tasks import TaskCreate, TaskRead, TaskUpdate

router = _fa.APIRouter(prefix="/tasks", tags=["tasks"])

# Who may call each operation, and which rows they get (see app/auth/access.py and app/auth/authorize.py).
_ACCESS = {
    "create": _authz.policy_dependency('Task', 'create', stamp=True, tenant=True),
    "delete": _authz.policy_dependency('Task', 'delete', tenant=True),
    "get": _authz.policy_dependency('Task', 'get', tenant=True),
    "head": _authz.policy_dependency('Task', 'head', tenant=True),
    "list": _authz.policy_dependency('Task', 'list', tenant=True),
    "replace": _authz.policy_dependency('Task', 'replace', tenant=True),
    "update": _authz.policy_dependency('Task', 'update', tenant=True),
}


@router.get("", response_model=_pagination.Page[TaskRead])
async def list_tasks(
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
    f_done: _t.Annotated[bool | None, _fa.Query(alias="done")] = None,
) -> _pagination.Page[TaskRead]:
    filters: dict[str, _t.Any] = {
        "done": f_done,
    }
    items, total = await TaskRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[TaskRead](
        items=[TaskRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=TaskRead)
async def get_tasks(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> TaskRead:
    item = await TaskRepository(session, **access.repo_kwargs).get(item_id)
    return TaskRead.model_validate(item)


@router.head("/{item_id}")
async def head_tasks(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await TaskRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Task not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=TaskRead, status_code=201)
async def create_tasks(
    body: TaskCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> TaskRead:
    item = await TaskRepository(session, **access.repo_kwargs).create(body.model_dump())
    return TaskRead.model_validate(item)


@router.put("/{item_id}", response_model=TaskRead)
async def replace_tasks(
    item_id: _uuid.UUID, body: TaskCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> TaskRead:
    item = await TaskRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return TaskRead.model_validate(item)


@router.patch("/{item_id}", response_model=TaskRead)
async def update_tasks(
    item_id: _uuid.UUID, body: TaskUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> TaskRead:
    item = await TaskRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return TaskRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_tasks(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await TaskRepository(session, **access.repo_kwargs).delete(item_id)
