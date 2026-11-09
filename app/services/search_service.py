"""Permission-filtered search over a project's imported records (B4-3, C21).

The caller (a builder member) picks the role to search AS; the filter itself lives in
`app.core.search` (object / row / field layers applied inside the query, adapter-independent).
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.search import FtsAdapter, OpenSearchAdapter, search
from app.exceptions import AppError
from app.models.data_import import ImportedRecord
from app.services.spec_service import SpecService

MAX_ROWS = 20_000
ADAPTERS: dict[str, Any] = {"fts": FtsAdapter(), "opensearch": OpenSearchAdapter()}


async def search_records(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    entity: str,
    query: str,
    as_role: str | None,
    adapter: str = "fts",
    as_tenant: str | None = None,
    as_user: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    spec = await SpecService(session).assemble(project_id)  # 404 for an unknown project
    if entity not in {e.name for e in spec.entities}:
        raise AppError("not_found", "entity not found", 404)
    if adapter not in ADAPTERS:
        raise AppError("validation_error", f"adapter must be one of {sorted(ADAPTERS)}", 422)
    known = {r.name for r in spec.auth.roles} if spec.auth is not None else set()
    if as_role is not None and as_role not in known:
        raise AppError("validation_error", "unknown role", 422)
    rows = (
        await session.execute(
            select(ImportedRecord.id, ImportedRecord.data)
            .where(ImportedRecord.project_id == project_id, ImportedRecord.entity_name == entity)
            .limit(MAX_ROWS + 1)
        )
    ).all()
    if len(rows) > MAX_ROWS:
        raise AppError("search_too_large", f"more than {MAX_ROWS} records to search", 422)
    records = [{**(data or {}), "id": str(rid)} for rid, data in rows]
    subject = {
        "id": as_user,
        "roles": [as_role] if as_role else [],
        "tenant_id": as_tenant,
    }
    out = search(spec, ADAPTERS[adapter], records, entity, query, subject, limit=limit)
    return {"entity": entity, "as_role": as_role, "adapter": adapter, **out}
