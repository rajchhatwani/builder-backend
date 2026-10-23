"""HTTP routes for Review (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import pagination as _pagination
from app.crud.reviews import ReviewRepository
from app.schemas.reviews import ReviewCreate, ReviewRead, ReviewUpdate

router = _fa.APIRouter(prefix="/reviews", tags=["reviews"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "delete": _access.access_dependency(roles=("manager", "marketing"), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("catalog", "customer", "fulfillment", "manager", "marketing", "support"), authenticate=True, tenant=True),
    "update": _access.access_dependency(roles=("manager", "marketing"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[ReviewRead])
async def list_reviews(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: created_at, rating"),
    ] = None,
    q: _t.Annotated[
        str | None, _fa.Query(description="Case-insensitive search in: body, title")
    ] = None,
    f_rating: _t.Annotated[int | None, _fa.Query(alias="rating")] = None,
    f_status: _t.Annotated[str | None, _fa.Query(alias="status")] = None,
) -> _pagination.Page[ReviewRead]:
    filters: dict[str, _t.Any] = {
        "rating": f_rating,
        "status": f_status,
    }
    items, total = await ReviewRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=q,
        sort=sort,
    )
    return _pagination.Page[ReviewRead](
        items=[ReviewRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ReviewRead)
async def get_reviews(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> ReviewRead:
    item = await ReviewRepository(session, **access.repo_kwargs).get(item_id)
    return ReviewRead.model_validate(item)


@router.post("", response_model=ReviewRead, status_code=201)
async def create_reviews(
    body: ReviewCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> ReviewRead:
    item = await ReviewRepository(session, **access.repo_kwargs).create(body.model_dump())
    return ReviewRead.model_validate(item)


@router.patch("/{item_id}", response_model=ReviewRead)
async def update_reviews(
    item_id: _uuid.UUID, body: ReviewUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> ReviewRead:
    item = await ReviewRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return ReviewRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_reviews(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await ReviewRepository(session, **access.repo_kwargs).delete(item_id)
