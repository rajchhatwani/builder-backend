"""HTTP routes for Document (generated). Custom routes belong in app/custom_routers/."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.auth import authorize as _authz
from app.core import errors as _errors
from app.core import pagination as _pagination
from app.crud.documents import DocumentRepository
from app.schemas.documents import DocumentCreate, DocumentRead, DocumentUpdate

router = _fa.APIRouter(prefix="/documents", tags=["documents"])

# Who may call each operation, and which rows they get (see app/auth/access.py and app/auth/authorize.py).
_ACCESS = {
    "create": _authz.policy_dependency('Document', 'create', stamp=True),
    "delete": _authz.policy_dependency('Document', 'delete'),
    "get": _authz.policy_dependency('Document', 'get'),
    "head": _authz.policy_dependency('Document', 'head'),
    "list": _authz.policy_dependency('Document', 'list'),
    "replace": _authz.policy_dependency('Document', 'replace'),
    "update": _authz.policy_dependency('Document', 'update'),
}


@router.get("", response_model=_pagination.Page[DocumentRead])
async def list_documents(
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
    f_status: _t.Annotated[str | None, _fa.Query(alias="status")] = None,
) -> _pagination.Page[DocumentRead]:
    filters: dict[str, _t.Any] = {
        "status": f_status,
    }
    items, total = await DocumentRepository(session, **access.repo_kwargs).list_items(
        page,
        filters={key: value for key, value in filters.items() if value is not None},
        search=None,
        sort=sort,
    )
    return _pagination.Page[DocumentRead](
        items=[DocumentRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=DocumentRead)
async def get_documents(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["get"])]
) -> DocumentRead:
    item = await DocumentRepository(session, **access.repo_kwargs).get(item_id)
    return DocumentRead.model_validate(item)


@router.head("/{item_id}")
async def head_documents(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["head"])]
) -> _fa.Response:
    if not await DocumentRepository(session, **access.repo_kwargs).exists(item_id):
        raise _errors.NotFoundError("Document not found")
    return _fa.Response(status_code=200)


@router.post("", response_model=DocumentRead, status_code=201)
async def create_documents(
    body: DocumentCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["create"])]
) -> DocumentRead:
    item = await DocumentRepository(session, **access.repo_kwargs).create(body.model_dump())
    return DocumentRead.model_validate(item)


@router.put("/{item_id}", response_model=DocumentRead)
async def replace_documents(
    item_id: _uuid.UUID, body: DocumentCreate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["replace"])]
) -> DocumentRead:
    item = await DocumentRepository(session, **access.repo_kwargs).replace(item_id, body.model_dump())
    return DocumentRead.model_validate(item)


@router.patch("/{item_id}", response_model=DocumentRead)
async def update_documents(
    item_id: _uuid.UUID, body: DocumentUpdate, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["update"])]
) -> DocumentRead:
    item = await DocumentRepository(session, **access.repo_kwargs).update(item_id, body.model_dump(exclude_unset=True))
    return DocumentRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_documents(
    item_id: _uuid.UUID, session: _db.SessionDep, access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS["delete"])]
) -> None:
    await DocumentRepository(session, **access.repo_kwargs).delete(item_id)
