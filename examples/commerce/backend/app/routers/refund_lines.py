"""HTTP routes for RefundLine (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.core import pagination as _pagination
from app.crud.refund_lines import RefundLineRepository
from app.schemas.refund_lines import RefundLineCreate, RefundLineRead

router = _fa.APIRouter(prefix="/refund_lines", tags=["refund_lines"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("manager", "support"), authenticate=True, tenant=True),
    "get": _access.access_dependency(roles=("fulfillment", "manager", "support"), authenticate=True, tenant=True),
    "list": _access.access_dependency(roles=("fulfillment", "manager", "support"), authenticate=True, tenant=True),
}


@router.get("", response_model=_pagination.Page[RefundLineRead])
async def list_refund_lines(
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
) -> _pagination.Page[RefundLineRead]:
    filters: dict[str, _t.Any] = {
    }
    items, total = await RefundLineRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[RefundLineRead](
        items=[RefundLineRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=RefundLineRead)
async def get_refund_lines(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> RefundLineRead:
    item = await RefundLineRepository(session, **access.repo_kwargs).get(item_id)
    return RefundLineRead.model_validate(item)


@router.post("", response_model=RefundLineRead, status_code=201)
async def create_refund_lines(
    body: RefundLineCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> RefundLineRead:
    item = await RefundLineRepository(session, **access.repo_kwargs).create(body.model_dump())
    return RefundLineRead.model_validate(item)
