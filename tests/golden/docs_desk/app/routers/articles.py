"""HTTP routes for Article (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.articles import ArticleRepository
from app.schemas.articles import ArticleCreate, ArticleRead, ArticleUpdate

router = _fa.APIRouter(prefix="/articles", tags=["articles"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("staff",)),
    "delete": _access.access_dependency(roles=("admin",)),
    "get": _access.access_dependency(match=('status', 'published')),
    "list": _access.access_dependency(match=('status', 'published')),
    "update": _access.access_dependency(roles=("staff",)),
}


@router.get("", response_model=_pagination.Page[ArticleRead])
async def list_articles(
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
) -> _pagination.Page[ArticleRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await ArticleRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[ArticleRead](
        items=[ArticleRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ArticleRead)
async def get_articles(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> ArticleRead:
    item = await ArticleRepository(session, **access.repo_kwargs).get(item_id)
    return ArticleRead.model_validate(item)


@router.head("/{item_id}")
async def head_articles(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await ArticleRepository(session).exists(item_id):
        raise _errors.NotFoundError("Article not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=ArticleRead, status_code=201)
async def create_articles(
    body: ArticleCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> ArticleRead:
    item = await ArticleRepository(session, **access.repo_kwargs).create(body.model_dump())
    return ArticleRead.model_validate(item)


@router.put("/{item_id}", response_model=ArticleRead)
async def replace_articles(
    item_id: _uuid.UUID, body: ArticleCreate, session: _db.SessionDep
) -> ArticleRead:
    item = await ArticleRepository(session).replace(item_id, body.model_dump())
    return ArticleRead.model_validate(item)


@router.patch("/{item_id}", response_model=ArticleRead)
async def update_articles(
    item_id: _uuid.UUID, body: ArticleUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> ArticleRead:
    item = await ArticleRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return ArticleRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_articles(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await ArticleRepository(session, **access.repo_kwargs).delete(item_id)
