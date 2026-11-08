"""HTTP routes for Secret (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.secrets import SecretRepository
from app.schemas.secrets import SecretCreate, SecretRead, SecretUpdate

router = _fa.APIRouter(prefix="/secrets", tags=["secrets"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin", "member"), stamp=True, authenticate=True),
    "list": _access.access_dependency(roles=("admin", "member"), owner=True, authenticate=True),
}


@router.get("", response_model=_pagination.Page[SecretRead])
async def list_secrets(
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
) -> _pagination.Page[SecretRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await SecretRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[SecretRead](
        items=[SecretRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=SecretRead)
async def get_secrets(item_id: _uuid.UUID, session: _db.SessionDep) -> SecretRead:
    item = await SecretRepository(session).get(item_id)
    return SecretRead.model_validate(item)


@router.head("/{item_id}")
async def head_secrets(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await SecretRepository(session).exists(item_id):
        raise _errors.NotFoundError("Secret not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=SecretRead, status_code=201)
async def create_secrets(
    body: SecretCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> SecretRead:
    item = await SecretRepository(session, **access.repo_kwargs).create(body.model_dump())
    return SecretRead.model_validate(item)


@router.put("/{item_id}", response_model=SecretRead)
async def replace_secrets(
    item_id: _uuid.UUID, body: SecretCreate, session: _db.SessionDep
) -> SecretRead:
    item = await SecretRepository(session).replace(item_id, body.model_dump())
    return SecretRead.model_validate(item)


@router.patch("/{item_id}", response_model=SecretRead)
async def update_secrets(
    item_id: _uuid.UUID, body: SecretUpdate, session: _db.SessionDep
) -> SecretRead:
    item = await SecretRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return SecretRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_secrets(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await SecretRepository(session).delete(item_id)
