"""HTTP routes for Ticket (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.auth import field_access as _fx
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.tickets import TicketRepository
from app.schemas.tickets import TicketCreate, TicketRead, TicketUpdate

router = _fa.APIRouter(prefix="/tickets", tags=["tickets"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("customer", "staff"), stamp=True, authenticate=True),
    "delete": _access.access_dependency(roles=("admin", "customer"), owner=True, authenticate=True),
    "get": _access.access_dependency(roles=("admin", "customer"), owner=True, authenticate=True),
    "list": _access.access_dependency(roles=("admin", "customer"), owner=True, admin_sees_all=True, authenticate=True),
    "replace": _access.access_dependency(roles=("admin", "customer"), owner=True, authenticate=True),
    "update": _access.access_dependency(roles=("admin", "customer"), owner=True, authenticate=True),
}


@router.get("", response_model=_pagination.Page[TicketRead], response_model_exclude_unset=True)
async def list_tickets(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: title"),
    ] = None,
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: internal_note, title")
    ] = None,
    f_title: _t.Annotated[str | None, _fa.Query(alias="title")] = None,
) -> _pagination.Page[TicketRead]:
    filters: dict[str, _t.Any] = {
        "title": f_title,
    }
    items, total = await TicketRepository(session, **access.repo_kwargs, hidden_fields=_fx.hidden_read("Ticket", access.user)).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[TicketRead](
        items=[_fx.shape("Ticket", access.user, TicketRead.model_validate(item)) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=TicketRead, response_model_exclude_unset=True)
async def get_tickets(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> TicketRead:
    item = await TicketRepository(session, **access.repo_kwargs).get(item_id)
    return _fx.shape("Ticket", access.user, TicketRead.model_validate(item))


@router.head("/{item_id}")
async def head_tickets(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await TicketRepository(session).exists(item_id):
        raise _errors.NotFoundError("Ticket not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=TicketRead, status_code=201, response_model_exclude_unset=True)
async def create_tickets(
    body: TicketCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> TicketRead:
    item = await TicketRepository(session, **access.repo_kwargs).create(_fx.payload("Ticket", access.user, body, "create"))
    return _fx.shape("Ticket", access.user, TicketRead.model_validate(item))


@router.put("/{item_id}", response_model=TicketRead, response_model_exclude_unset=True)
async def replace_tickets(
    item_id: _uuid.UUID, body: TicketCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> TicketRead:
    item = await TicketRepository(session, **access.repo_kwargs).replace(item_id, _fx.payload("Ticket", access.user, body, "replace"))
    return _fx.shape("Ticket", access.user, TicketRead.model_validate(item))


@router.patch("/{item_id}", response_model=TicketRead, response_model_exclude_unset=True)
async def update_tickets(
    item_id: _uuid.UUID, body: TicketUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> TicketRead:
    item = await TicketRepository(session, **access.repo_kwargs).update(item_id, _fx.payload("Ticket", access.user, body, "update"))
    return _fx.shape("Ticket", access.user, TicketRead.model_validate(item))


@router.delete("/{item_id}", status_code=204)
async def delete_tickets(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await TicketRepository(session, **access.repo_kwargs).delete(item_id)
