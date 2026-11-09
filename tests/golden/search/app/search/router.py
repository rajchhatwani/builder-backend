"""Search routes (generated): GET /<entity>/search?q=&limit= for entities with searchable fields.

Same caller access as the entity's list endpoint (roles, tenant, owner / row scope, policy). Fields the
caller may not read are not searched and not returned. Engine: SEARCH_BACKEND (see app/search/config.py)."""

import typing as _t

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.auth import field_access as _fx
from app.crud.tickets import TicketRepository
from app.routers.tickets import _ACCESS as _ACCESS_tickets
from app.schemas.tickets import TicketRead
from app.search import service as _service

router = _fa.APIRouter(tags=["search"])
_Q = _t.Annotated[str, _fa.Query(min_length=1, max_length=200, description="Words to look for")]
_LIMIT = _t.Annotated[int, _fa.Query(ge=1, le=100)]


@router.get(
    "/tickets/search",
    response_model=_service.SearchPage[TicketRead], response_model_exclude_unset=True,
)
async def search_tickets(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_tickets["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[TicketRead]:
    """Search internal_note, title of Ticket."""
    hidden = _fx.hidden_read("Ticket", access.user)
    repo = TicketRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[TicketRead](
        items=[_fx.shape("Ticket", access.user, TicketRead.model_validate(row)) for row in rows],
        total=total,
        limit=limit,
    )
