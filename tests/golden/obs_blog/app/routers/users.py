"""HTTP routes for User (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.users import UserRepository
from app.schemas.users import UserCreate, UserRead, UserUpdate

router = _fa.APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=_pagination.Page[UserRead])
async def list_users(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: email"),
    ] = None,
    f_email: _t.Annotated[str | None, _fa.Query(alias="email")] = None,
) -> _pagination.Page[UserRead]:
    filters: dict[str, _t.Any] = {
        "email": f_email,
    }
    items, total = await UserRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[UserRead](
        items=[UserRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=UserRead)
async def get_users(item_id: _uuid.UUID, session: _db.SessionDep) -> UserRead:
    item = await UserRepository(session).get(item_id)
    return UserRead.model_validate(item)


@router.head("/{item_id}")
async def head_users(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await UserRepository(session).exists(item_id):
        raise _errors.NotFoundError("User not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=UserRead, status_code=201)
async def create_users(body: UserCreate, session: _db.SessionDep) -> UserRead:
    item = await UserRepository(session).create(body.model_dump())
    return UserRead.model_validate(item)


@router.put("/{item_id}", response_model=UserRead)
async def replace_users(
    item_id: _uuid.UUID, body: UserCreate, session: _db.SessionDep
) -> UserRead:
    item = await UserRepository(session).replace(item_id, body.model_dump())
    return UserRead.model_validate(item)


@router.patch("/{item_id}", response_model=UserRead)
async def update_users(
    item_id: _uuid.UUID, body: UserUpdate, session: _db.SessionDep
) -> UserRead:
    item = await UserRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return UserRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_users(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await UserRepository(session).delete(item_id)
