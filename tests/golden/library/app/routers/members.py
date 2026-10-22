"""HTTP routes for Member (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.members import MemberRepository
from app.schemas.members import MemberCreate, MemberRead, MemberUpdate

router = _fa.APIRouter(prefix="/members", tags=["members"])


@router.get("", response_model=_pagination.Page[MemberRead])
async def list_members(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: none"),
    ] = None,
    f_email: _t.Annotated[str | None, _fa.Query(alias="email")] = None,
) -> _pagination.Page[MemberRead]:
    filters: dict[str, _t.Any] = {
        "email": f_email,
    }
    items, total = await MemberRepository(session).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[MemberRead](
        items=[MemberRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=MemberRead)
async def get_members(item_id: _uuid.UUID, session: _db.SessionDep) -> MemberRead:
    item = await MemberRepository(session).get(item_id)
    return MemberRead.model_validate(item)


@router.head("/{item_id}")
async def head_members(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await MemberRepository(session).exists(item_id):
        raise _errors.NotFoundError("Member not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=MemberRead, status_code=201)
async def create_members(body: MemberCreate, session: _db.SessionDep) -> MemberRead:
    item = await MemberRepository(session).create(body.model_dump())
    return MemberRead.model_validate(item)


@router.put("/{item_id}", response_model=MemberRead)
async def replace_members(
    item_id: _uuid.UUID, body: MemberCreate, session: _db.SessionDep
) -> MemberRead:
    item = await MemberRepository(session).replace(item_id, body.model_dump())
    return MemberRead.model_validate(item)


@router.patch("/{item_id}", response_model=MemberRead)
async def update_members(
    item_id: _uuid.UUID, body: MemberUpdate, session: _db.SessionDep
) -> MemberRead:
    item = await MemberRepository(session).update(item_id, body.model_dump(exclude_unset=True))
    return MemberRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_members(item_id: _uuid.UUID, session: _db.SessionDep) -> None:
    await MemberRepository(session).delete(item_id)
