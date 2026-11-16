"""B1-032 F-0276: side connections (refusal events, project advisory lock) must not need the caller's pool."""

import asyncio
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.services.usage_service import UsageService
from app.services.workspace_service import WorkspaceService


async def test_side_connections_work_with_the_caller_pool_exhausted(client: AsyncClient, database_url: str) -> None:
    org = uuid.UUID((await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()["id"])
    tiny = create_async_engine(database_url, pool_size=1, max_overflow=0, pool_timeout=1)
    try:
        async with AsyncSession(tiny) as s:
            await s.connection()  # the request's own (only) pooled connection
            svc = UsageService(s)
            await asyncio.wait_for(svc._record_refused(org, None, "previews.started", 1), 10)
            ws = WorkspaceService.__new__(WorkspaceService)
            ws.session = s  # type: ignore[attr-defined]
            async with ws._project_lock(uuid.uuid4()):
                pass
    finally:
        await tiny.dispose()
