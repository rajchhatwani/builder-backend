"""Search: the same access scope as the entity's list endpoint, plus the field rules.

Both engines produce rows only through `repo._alive()` (soft delete, owner / tenant / role scope, abac /
pbac policy), so a row the caller may not list is never a candidate, never a hit and never in `total`.
Fields the caller may not read are neither searched nor returned (callers pass them in `hidden`).
"""

import uuid
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel

from app.core.errors import AppError
from app.crud._base import Repository
from app.search import config
from app.search.adapters import SearchUnavailable, get_adapter

MAX_LIMIT = 100
MAX_Q = 200
_CANDIDATES_PER_HIT = 5
_CANDIDATES_MAX = 500
_SIMPLE = sa.literal_column("'simple'::regconfig")
_SPACE = sa.literal_column("' '")


class SearchPage[T](BaseModel):
    items: list[T]
    total: int
    limit: int


def clean(q: str) -> str:
    q = q.strip()
    if not q:
        raise AppError("invalid_query", "q must not be empty", 422, [{"field": "q"}])
    return q


async def find(
    repo: Repository[Any], q: str, limit: int, hidden: frozenset[str] = frozenset()
) -> tuple[list[Any], int]:
    """(rows, total) for `q`. `total` counts only rows the caller may list (for opensearch: the verified
    candidates the engine returned, at most 5x limit)."""
    q = clean(q)
    limit = max(1, min(limit, MAX_LIMIT))
    fields = tuple(n for n in repo.searchable if n not in hidden)
    if not fields:
        return [], 0
    conditions = repo._alive()
    if config.backend() == config.FTS:
        return await _fts(repo, q, limit, fields, conditions)
    return await _indexed(repo, q, limit, fields, conditions)


async def _fts(
    repo: Repository[Any], q: str, limit: int, fields: tuple[str, ...], conditions: list[Any]
) -> tuple[list[Any], int]:
    document = sa.func.to_tsvector(
        _SIMPLE, sa.func.concat_ws(_SPACE, *[sa.cast(repo._col(n), sa.Text) for n in fields])
    )
    query = sa.func.plainto_tsquery(_SIMPLE, q)  # q is a bound parameter
    where = [*conditions, document.op("@@")(query)]
    total = (
        await repo.session.execute(sa.select(sa.func.count()).select_from(repo.model).where(*where))
    ).scalar_one()
    stmt = (
        sa.select(repo.model)
        .where(*where)
        .order_by(sa.func.ts_rank(document, query).desc(), repo._col("id"))
        .limit(limit)
        .options(*repo._loaders())
    )
    return list((await repo.session.execute(stmt)).scalars().all()), total


async def _indexed(
    repo: Repository[Any], q: str, limit: int, fields: tuple[str, ...], conditions: list[Any]
) -> tuple[list[Any], int]:
    adapter = get_adapter()
    assert adapter is not None
    try:
        raw = await adapter.query_ids(
            repo.model.__name__, q, fields, min(limit * _CANDIDATES_PER_HIT, _CANDIDATES_MAX)
        )
    except SearchUnavailable as exc:
        raise AppError("search_unavailable", "the search engine is not available", 503) from exc
    ids: list[uuid.UUID] = []
    for value in raw:
        try:
            ids.append(uuid.UUID(str(value)))
        except ValueError:
            continue  # a stale or foreign id is simply not a candidate
    if not ids:
        return [], 0
    stmt = (
        sa.select(repo.model)
        .where(repo._col("id").in_(ids), *conditions)  # the access scope decides, never the index
        .options(*repo._loaders())
    )
    by_id = {row.id: row for row in (await repo.session.execute(stmt)).scalars().all()}
    rows = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
    return rows[:limit], len(rows)
