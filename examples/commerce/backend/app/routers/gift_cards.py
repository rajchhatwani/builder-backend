"""HTTP routes for GiftCard (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.gift_cards import GiftCardRepository
from app.schemas.gift_cards import GiftCardCreate, GiftCardRead, GiftCardUpdate

router = _fa.APIRouter(prefix="/gift_cards", tags=["gift_cards"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("manager", "marketing"), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("manager",), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "head": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "replace": _access.access_dependency(roles=("manager", "marketing"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("manager", "marketing"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[GiftCardRead])
async def list_gift_cards(
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
    f_code: _t.Annotated[str | None, _fa.Query(alias="code")] = None,
    f_disabled: _t.Annotated[bool | None, _fa.Query(alias="disabled")] = None,
) -> _pagination.Page[GiftCardRead]:
    filters: dict[str, _t.Any] = {
        "code": f_code,
        "disabled": f_disabled,
    }
    items, total = await GiftCardRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[GiftCardRead](
        items=[GiftCardRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=GiftCardRead)
async def get_gift_cards(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> GiftCardRead:
    item = await GiftCardRepository(session, **access.repo_kwargs).get(item_id)
    return GiftCardRead.model_validate(item)


@router.head("/{item_id}")
async def head_gift_cards(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await GiftCardRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("GiftCard not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=GiftCardRead, status_code=201)
async def create_gift_cards(
    body: GiftCardCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> GiftCardRead:
    item = await GiftCardRepository(session, **access.repo_kwargs).create(body.model_dump())
    return GiftCardRead.model_validate(item)


@router.put("/{item_id}", response_model=GiftCardRead)
async def replace_gift_cards(
    item_id: _uuid.UUID, body: GiftCardCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> GiftCardRead:
    item = await GiftCardRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return GiftCardRead.model_validate(item)


@router.patch("/{item_id}", response_model=GiftCardRead)
async def update_gift_cards(
    item_id: _uuid.UUID, body: GiftCardUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> GiftCardRead:
    item = await GiftCardRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return GiftCardRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_gift_cards(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await GiftCardRepository(session, **access.repo_kwargs).delete(item_id)
