"""Search routes (generated): GET /<entity>/search?q=&limit= for entities with searchable fields.

Same caller access as the entity's list endpoint (roles, tenant, owner / row scope, policy). Fields the
caller may not read are not searched and not returned. Engine: SEARCH_BACKEND (see app/search/config.py)."""

import typing as _t

import fastapi as _fa

from app import db as _db
from app.crud.posts import PostRepository
from app.schemas.posts import PostRead
from app.search import service as _service

router = _fa.APIRouter(tags=["search"])
_Q = _t.Annotated[str, _fa.Query(min_length=1, max_length=200, description="Words to look for")]
_LIMIT = _t.Annotated[int, _fa.Query(ge=1, le=100)]


@router.get(
    "/posts/search",
    response_model=_service.SearchPage[PostRead],
)
async def search_posts(
    session: _db.SessionDep,
    q: _Q,
    limit: _LIMIT = 20,
) -> _service.SearchPage[PostRead]:
    """Search body, title of Post."""
    hidden = frozenset[str]()
    repo = PostRepository(session)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[PostRead](
        items=[PostRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )
