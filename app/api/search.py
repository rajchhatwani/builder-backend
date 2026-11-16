"""Permission-filtered search over imported records (B4-3, C21).

GET  /projects/{project_id}/search?entity=&q=&as_role=&adapter=fts|opensearch   (viewer)
POST /projects/{project_id}/search/reindex                                    (editor)
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.exceptions import AppError
from app.services.search_service import reindex_project, search_records

router = APIRouter(prefix="/projects/{project_id}", tags=["search"])


@router.get("/search")
async def search_project(
    request: Request,
    project_id: uuid.UUID,
    entity: str = Query(min_length=1, max_length=120),
    q: str = Query(min_length=1, max_length=200),
    as_role: str | None = Query(default=None, max_length=120),
    adapter: str = Query(default="fts", max_length=20),
    as_tenant: str | None = Query(default=None, max_length=64),
    as_user: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if as_role is not None or as_tenant is not None or as_user is not None:
        # Simulating another role/user/tenant would show fields and rows the caller's own role
        # may not read (C7), so only editors and owners may do it.
        role = getattr(request.state, "member_role", None)
        if str(getattr(role, "value", role)) not in ("editor", "owner"):
            raise AppError("forbidden", "searching as another role needs the editor role", 403)
    return await search_records(
        db, project_id, entity=entity, query=q, as_role=as_role, adapter=adapter,
        as_tenant=as_tenant, as_user=as_user, limit=limit,
    )  # fmt: skip


@router.post("/search/reindex")
async def reindex(project_id: uuid.UUID, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Editor-only (the project guard requires an editor for every non-GET method)."""
    return await reindex_project(db, project_id)
