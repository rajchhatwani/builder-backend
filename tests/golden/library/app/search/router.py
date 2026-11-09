"""Search routes (generated): GET /<entity>/search?q=&limit= for entities with searchable fields.

Same caller access as the entity's list endpoint (roles, tenant, owner / row scope, policy). Fields the
caller may not read are not searched and not returned. Engine: SEARCH_BACKEND (see app/search/config.py)."""

import typing as _t

import fastapi as _fa

from app import db as _db
from app.crud.authors import AuthorRepository
from app.crud.books import BookRepository
from app.schemas.authors import AuthorRead
from app.schemas.books import BookRead
from app.search import service as _service

router = _fa.APIRouter(tags=["search"])
_Q = _t.Annotated[str, _fa.Query(min_length=1, max_length=200, description="Words to look for")]
_LIMIT = _t.Annotated[int, _fa.Query(ge=1, le=100)]


@router.get(
    "/authors/search",
    response_model=_service.SearchPage[AuthorRead],
)
async def search_authors(
    session: _db.SessionDep,
    q: _Q,
    limit: _LIMIT = 20,
) -> _service.SearchPage[AuthorRead]:
    """Search name of Author."""
    hidden = frozenset[str]()
    repo = AuthorRepository(session)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[AuthorRead](
        items=[AuthorRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )


@router.get(
    "/books/search",
    response_model=_service.SearchPage[BookRead],
)
async def search_books(
    session: _db.SessionDep,
    q: _Q,
    limit: _LIMIT = 20,
) -> _service.SearchPage[BookRead]:
    """Search isbn, title of Book."""
    hidden = frozenset[str]()
    repo = BookRepository(session)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[BookRead](
        items=[BookRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )
