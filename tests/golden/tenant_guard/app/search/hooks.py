"""Keeps the external index in step with the database (after_commit; failures are logged, never fail a
write). With SEARCH_BACKEND=fts there is nothing to keep: the hook returns at once."""

from typing import Any

import structlog

from app.crud.lifecycle import Hook, HookContext
from app.search.adapters import get_adapter

logger = structlog.get_logger()


def build_document(item: Any, fields: tuple[str, ...]) -> dict[str, str]:
    """The indexed document of one record: its searchable values as text (also used by the reindex command)."""
    return {n: str(getattr(item, n)) for n in fields if getattr(item, n, None) is not None}


def hooks_for(entity: str, fields: tuple[str, ...]) -> dict[str, tuple[Hook, ...]]:
    async def sync(ctx: HookContext) -> None:
        adapter = get_adapter()
        item: Any = ctx.item
        if adapter is None or item is None:
            return
        doc_id = str(item.id)
        try:
            if ctx.op == "delete" or getattr(item, "deleted_at", None) is not None:
                await adapter.delete(entity, doc_id)
            else:
                await adapter.index(entity, doc_id, build_document(item, fields))
        except Exception as exc:
            logger.warning("search_index_failed", entity=entity, error=type(exc).__name__)

    return {"after_commit": (sync,)}


def attach(
    entity: str, fields: tuple[str, ...], existing: dict[str, tuple[Hook, ...]]
) -> dict[str, tuple[Hook, ...]]:
    merged = dict(existing)
    for stage, funcs in hooks_for(entity, fields).items():
        merged[stage] = (*merged.get(stage, ()), *funcs)
    return merged
