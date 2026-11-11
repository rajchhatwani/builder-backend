"""Loads the requirements map of a project for the coverage gate (G13). Read-only, capped."""

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.requirements import RequirementItem

MAX_ITEMS = 500


async def load_requirement_views(session: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]] | None:
    """The items of the project's requirements map as plain dicts; None when it has no items at all."""
    rows = (
        await session.execute(
            select(RequirementItem)
            .where(RequirementItem.project_id == project_id)
            .order_by(RequirementItem.created_at, RequirementItem.id)
            .limit(MAX_ITEMS)
        )
    ).scalars().all()
    if not rows:
        return None
    return [
        {"id": str(r.id), "kind": r.kind, "text": r.text, "status": r.status, "covered_by": r.covered_by}
        for r in rows
    ]


def requirements_digest(items: list[dict[str, Any]] | None) -> str:
    """Folded into the gate-report cache key: a changed map must not reuse an old report."""
    return hashlib.sha256(json.dumps(items, sort_keys=True, default=str).encode()).hexdigest()[:16]
