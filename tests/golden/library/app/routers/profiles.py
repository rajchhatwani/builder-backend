"""HTTP routes for Profile (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.profiles import ProfileRepository
from app.schemas.profiles import ProfileCreate, ProfileRead, ProfileUpdate

router = _fa.APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("", response_model=_pagination.Page[ProfileRead])
async def list_profiles(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: none"),
    ] = None,
) -> _pagination.Page[ProfileRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await ProfileRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[ProfileRead](
        items=[ProfileRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ProfileRead)
async def get_profiles(item_id: _uuid.UUID, session: _db.SessionDep) -> ProfileRead:
    item = await ProfileRepository(session).get(item_id)
    return ProfileRead.model_validate(item)


@router.head("/{item_id}")
async def head_profiles(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await ProfileRepository(session).exists(item_id):
        raise _errors.NotFoundError("Profile not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=ProfileRead, status_code=201)
async def create_profiles(body: ProfileCreate, session: _db.SessionDep) -> ProfileRead:
    item = await ProfileRepository(session).create(body.model_dump())
    return ProfileRead.model_validate(item)


@router.put("/{item_id}", response_model=ProfileRead)
async def replace_profiles(
    item_id: _uuid.UUID, body: ProfileCreate, session: _db.SessionDep
) -> ProfileRead:
    item = await ProfileRepository(session).replace(item_id, body.model_dump())
    return ProfileRead.model_validate(item)


@router.patch("/{item_id}", response_model=ProfileRead)
async def update_profiles(
    item_id: _uuid.UUID, body: ProfileUpdate, session: _db.SessionDep
) -> ProfileRead:
    item = await ProfileRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return ProfileRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_profiles(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await ProfileRepository(session).delete(item_id)
