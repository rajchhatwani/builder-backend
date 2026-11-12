"""CP-5V: a committed platform import fires the same after-commit effects as a normal write: a history
entry (audit log), a realtime event, and a search index that already knows the rows (the platform search
reads the table at query time, so a committed row is findable at once)."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.platform import AuditLog
from app.models.realtime import RealtimeEvent
from tests.api.conftest import ClientFor
from tests.api.test_search_api import find, seeded


async def test_commit_writes_a_history_entry(
    client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    client: AsyncClient = await client_for("a@example.com")
    pid = await seeded(client, row_rule=None)
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(AuditLog).where(AuditLog.project_id == uuid.UUID(pid), AuditLog.action == "import.commit")
            )
        ).scalars().all()
    assert len(rows) == 1 and rows[0].detail["created"] == 3


async def test_commit_publishes_a_realtime_event_without_row_data(
    client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    client: AsyncClient = await client_for("a@example.com")
    pid = await seeded(client, row_rule=None)
    async with session_factory() as db:
        events = (
            await db.execute(select(RealtimeEvent).where(RealtimeEvent.project_id == uuid.UUID(pid)))
        ).scalars().all()
    committed = [e for e in events if e.type == "import.committed"]
    assert len(committed) == 1 and committed[0].data["created"] == 3
    assert "Anna" not in str(committed[0].data)


async def test_committed_rows_are_in_the_search_index_at_once(client_for: ClientFor) -> None:
    client: AsyncClient = await client_for("a@example.com")
    pid = await seeded(client, row_rule=None)
    for adapter in ("fts", "opensearch"):
        hits = await find(client, pid, "chess", "admin", adapter)
        assert hits["total"] == 2
