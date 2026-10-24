"""HTTP routes for Label (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.auth import authorize as _authz
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.labels import LabelRepository
from app.schemas.labels import LabelCreate, LabelRead, LabelUpdate

router = _fa.APIRouter(prefix="/labels", tags=["labels"])

# Who may call each operation, and which rows they get (see app/auth/access.py and app/auth/authorize.py).
_ACCESS = {
    "create": _authz.policy_dependency('Label', 'create', tenant=True),
    "delete": _authz.policy_dependency('Label', 'delete', tenant=True),
    "get": _authz.policy_dependency('Label', 'get', tenant=True),
    "head": _authz.policy_dependency('Label', 'head', tenant=True),
    "list": _authz.policy_dependency('Label', 'list', tenant=True),
    "replace": _authz.policy_dependency('Label', 'replace', tenant=True),
    "update": _authz.policy_dependency('Label', 'update', tenant=True),
}


@router.get("", response_model=_pagination.Page[LabelRead])
async def list_labels(
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
) -> _pagination.Page[LabelRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await LabelRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[LabelRead](
        items=[LabelRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=LabelRead)
async def get_labels(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> LabelRead:
    item = await LabelRepository(session, **access.repo_kwargs).get(item_id)
    return LabelRead.model_validate(item)


@router.head("/{item_id}")
async def head_labels(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await LabelRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Label not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=LabelRead, status_code=201)
async def create_labels(
    body: LabelCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> LabelRead:
    item = await LabelRepository(session, **access.repo_kwargs).create(body.model_dump())
    return LabelRead.model_validate(item)


@router.put("/{item_id}", response_model=LabelRead)
async def replace_labels(
    item_id: _uuid.UUID, body: LabelCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> LabelRead:
    item = await LabelRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return LabelRead.model_validate(item)


@router.patch("/{item_id}", response_model=LabelRead)
async def update_labels(
    item_id: _uuid.UUID, body: LabelUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> LabelRead:
    item = await LabelRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return LabelRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_labels(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await LabelRepository(session, **access.repo_kwargs).delete(item_id)
