"""HTTP routes for Expense (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.auth import field_access as _fx
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.expenses import ExpenseRepository
from app.schemas.expenses import ExpenseCreate, ExpenseRead, ExpenseUpdate

router = _fa.APIRouter(prefix="/expenses", tags=["expenses"])

# Who may call each operation, and which rows they get (see app/auth/access.py).
_ACCESS = {
    "create": _access.access_dependency(roles=("admin", "staff"), stamp=True, authenticate=True),
    "delete": _access.access_dependency(roles=("admin", "staff"), owner=True, authenticate=True),
    "get": _access.access_dependency(roles=("admin", "staff"), owner=True, authenticate=True),
    "list": _access.access_dependency(roles=("admin", "staff"), owner=True, admin_sees_all=True, authenticate=True),
    "replace": _access.access_dependency(roles=("admin", "staff"), owner=True, authenticate=True),
    "update": _access.access_dependency(roles=("admin", "staff"), owner=True, authenticate=True),
}


@router.get("", response_model=_pagination.Page[ExpenseRead], response_model_exclude_unset=True)
async def list_expenses(
    session: _db.SessionDep,
    page: _t.Annotated[
        _pagination.PageParams,
        _fa.Depends(_pagination.page_params(20, 100)),
    ],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["list"])],
    sort: _t.Annotated[
        str | None,
        _fa.Query(description="Comma-separated fields, '-' prefix for descending. Allowed: category"),
    ] = None,
    f_category: _t.Annotated[str | None, _fa.Query(alias="category")] = None,
) -> _pagination.Page[ExpenseRead]:
    filters: dict[str, _t.Any] = {
        "category": f_category,
    }
    items, total = await ExpenseRepository(session, **access.repo_kwargs, hidden_fields=_fx.hidden_read("Expense", access.user)).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[ExpenseRead](
        items=[_fx.shape("Expense", access.user, ExpenseRead.model_validate(item)) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ExpenseRead, response_model_exclude_unset=True)
async def get_expenses(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> ExpenseRead:
    item = await ExpenseRepository(session, **access.repo_kwargs).get(item_id)
    return _fx.shape("Expense", access.user, ExpenseRead.model_validate(item))


@router.head("/{item_id}")
async def head_expenses(item_id: _uuid.UUID, session: _db.SessionDep) -> _fa.Response:
    if not await ExpenseRepository(session).exists(item_id):
        raise _errors.NotFoundError("Expense not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=ExpenseRead, status_code=201, response_model_exclude_unset=True)
async def create_expenses(
    body: ExpenseCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> ExpenseRead:
    item = await ExpenseRepository(session, **access.repo_kwargs).create(_fx.payload("Expense", access.user, body, "create"))
    return _fx.shape("Expense", access.user, ExpenseRead.model_validate(item))


@router.put("/{item_id}", response_model=ExpenseRead, response_model_exclude_unset=True)
async def replace_expenses(
    item_id: _uuid.UUID, body: ExpenseCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> ExpenseRead:
    item = await ExpenseRepository(session, **access.repo_kwargs).replace(item_id, _fx.payload("Expense", access.user, body, "replace"))
    return _fx.shape("Expense", access.user, ExpenseRead.model_validate(item))


@router.patch("/{item_id}", response_model=ExpenseRead, response_model_exclude_unset=True)
async def update_expenses(
    item_id: _uuid.UUID, body: ExpenseUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> ExpenseRead:
    item = await ExpenseRepository(session, **access.repo_kwargs).update(item_id, _fx.payload("Expense", access.user, body, "update"))
    return _fx.shape("Expense", access.user, ExpenseRead.model_validate(item))


@router.delete("/{item_id}", status_code=204)
async def delete_expenses(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await ExpenseRepository(session, **access.repo_kwargs).delete(item_id)
