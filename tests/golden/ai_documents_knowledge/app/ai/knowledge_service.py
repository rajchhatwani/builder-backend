"""Knowledge library service (generated). The rules, in one place.

PERMISSIONS FIRST. A source is visible to its creator and to callers who hold one of its `allowed_roles` (an owner-only
source has no roles). `_visibility()` is ONE SQL condition that is part of the WHERE clause of every read (list, search,
ask retrieval, delete lookup), so it runs BEFORE ranking and LIMIT: a chunk the caller may not see is never selected, never
counted, never cited and never sent to the model. Roles are read from the caller's CURRENT user row on every request, so a
role change takes effect at once. Multi-tenant projects additionally scope everything by tenant.

RETRIEVAL. Full-text search (Postgres tsvector, 'simple' configuration, OR of the query words) blended with a deterministic
FAKE embedding: score = 0.6 * ts_rank(normalised to 0..1) + 0.4 * cosine(query, chunk), as integer basis points. There is
no pgvector in the default Postgres image; the adapter interface (`Embedder`) is where a real embedding model or a pgvector
column plugs in: `embed(text)` returns a fixed-length integer vector, the stored vector and its squared norm are used by
the SQL cosine. Swap the class and re-index; the permission condition does not change.

ASK. Retrieve permitted chunks -> ONE gateway call on stage `knowledge.STAGE` (cost ledger, budget, idempotency like any
call) whose messages carry only those chunks -> answer + citations of those chunks. With no permitted chunk the model is NOT
called: grounded false, answer "", no citations, call_id null. ASK ROLE RULE: asking spends gateway budget, so the caller
needs a gateway call role (packs.ai.gateway.roles.call_roles or manage_roles; empty call_roles = any signed-in user), the
same gate as POST /ai/complete; otherwise 403 forbidden, before any retrieval.

SOURCE CAP. `max_sources` is a resource cap on the TENANT total (also sources the caller cannot see). The limit_reached
message carries no count, so it does not disclose how many invisible sources exist.
"""

import hashlib
import re
import typing as _t
import uuid as _uuid
from datetime import UTC, datetime

import sqlalchemy as _sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import knowledge_config as _config
from app.ai import knowledge_schemas as _s
from app.ai import schemas as _gw
from app.ai import service as _gateway
from app.ai.knowledge_models import AiKnowledgeChunk, AiKnowledgeSource
from app.auth.service import effective_roles
from app.core.errors import AppError

_WORD = re.compile(r"[^\W_]+")
_STOP = frozenset(
    "a an and are as at be but by do does for from how i in is it of on or that the this to was what when where which who why with you".split()
)
QUOTE_CHARS = 300
MIN_COSINE = 0.3  # a chunk without a full-text match still qualifies above this cosine


def _now() -> datetime:
    return datetime.now(UTC)


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 1 and w not in _STOP]


class Embedder(_t.Protocol):
    """Adapter interface: a fixed-length integer vector per text (the fake one below needs no network or model)."""

    dim: int

    def embed(self, text: str) -> list[int]: ...


class FakeEmbedder:
    """Hashed bag of words: each word adds 1 to bucket sha256(word)[:4] % dim (capped at 255). Deterministic."""

    dim = 128

    def embed(self, text: str) -> list[int]:
        vector = [0] * self.dim
        for word in _words(text):
            bucket = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % self.dim
            vector[bucket] = min(255, vector[bucket] + 1)
        return vector


EMBEDDER: Embedder = FakeEmbedder()


def chunk_text(text: str, size: int) -> list[str]:
    """Pieces of at most `size` characters, cut at the last whitespace of the second half when there is one."""
    pieces: list[str] = []
    i, n = 0, len(text)
    while i < n:
        j = min(n, i + size)
        if j < n:
            cut = max(text.rfind(" ", i + size // 2, j), text.rfind("\n", i + size // 2, j))
            if cut > i:
                j = cut + 1
        piece = text[i:j].strip()
        if piece:
            pieces.append(piece)
        i = j
    return pieces


def _scoped(stmt: _t.Any, model: _t.Any, tenant: _uuid.UUID | None) -> _t.Any:
    return stmt.where(model.tenant_id == tenant) if tenant is not None else stmt


def _visibility(user: _t.Any) -> _t.Any:
    """The permission filter on a source (ORM form): creator, or a role of the source. Applied inside the query."""
    roles = sorted(effective_roles(user.roles))
    return _sa.or_(AiKnowledgeSource.owner_id == user.id, AiKnowledgeSource.allowed_roles.overlap(roles))


# the same filter in the raw SQL of `search` (s = ai_knowledge_sources)
_VISIBLE_SQL = "(s.owner_id = :uid OR s.allowed_roles && CAST(:roles AS text[]))"


def _source_out(s: AiKnowledgeSource) -> _s.SourceOut:
    return _s.SourceOut(
        id=s.id,
        title=s.title,
        allowed_roles=list(s.allowed_roles),
        owner_only=s.owner_only,
        owner_id=s.owner_id,
        chunk_count=s.chunk_count,
        created_at=s.created_at,
    )


async def create_source(session: AsyncSession, user: _t.Any, body: _s.SourceIn) -> _s.SourceOut:
    tenant = _gateway.tenant_of(user)
    owner: _uuid.UUID = user.id
    roles = sorted(set(body.allowed_roles or []))
    if roles and body.owner_only:
        raise AppError("visibility_conflict", "give allowed_roles or owner_only, not both", 422)
    if not roles and not body.owner_only:
        raise AppError("visibility_required", "give allowed_roles (a non-empty list) or owner_only true", 422)
    unknown = [r for r in roles if r not in _config.KNOWN_ROLES]
    if unknown:
        raise AppError("unknown_role", f"unknown role {unknown[0][:40]!r}", 422)
    if len(body.text) > _config.MAX_TEXT_CHARS:
        raise AppError("content_too_large", f"the text is longer than {_config.MAX_TEXT_CHARS} characters", 422)
    count = await session.scalar(_scoped(_sa.select(_sa.func.count()).select_from(AiKnowledgeSource), AiKnowledgeSource, tenant))
    if (count or 0) >= _config.MAX_SOURCES:
        # the cap counts every source of the tenant, also ones the caller cannot see: no number in the message
        raise AppError("limit_reached", "the knowledge base has reached its source limit", 422)
    pieces = chunk_text(body.text, _config.CHUNK_CHARS)
    if not pieces:
        raise AppError("validation_error", "the text has no content", 422)
    source = AiKnowledgeSource(
        id=_uuid.uuid4(),
        title=body.title,
        owner_id=owner,
        owner_only=bool(body.owner_only),
        allowed_roles=[] if body.owner_only else roles,
        chunk_count=len(pieces),
        created_at=_now(),
    )
    if tenant is not None:
        source.tenant_id = tenant
    session.add(source)
    await session.flush()
    rows: list[dict[str, _t.Any]] = []
    for position, piece in enumerate(pieces):
        vector = EMBEDDER.embed(piece)
        row: dict[str, _t.Any] = {
            "id": _uuid.uuid4(),
            "source_id": source.id,
            "position": position,
            "text": piece,
            "embedding": vector,
            "emb_norm2": sum(v * v for v in vector),
        }
        if tenant is not None:
            row["tenant_id"] = tenant
        rows.append(row)
    await session.execute(_sa.insert(AiKnowledgeChunk), rows)
    out = _source_out(source)
    await session.commit()
    return out


async def list_sources(session: AsyncSession, user: _t.Any, limit: int, offset: int) -> tuple[list[_s.SourceOut], int]:
    tenant = _gateway.tenant_of(user)
    where = _visibility(user)
    total = await session.scalar(_scoped(_sa.select(_sa.func.count()).select_from(AiKnowledgeSource).where(where), AiKnowledgeSource, tenant))
    rows = (
        await session.execute(
            _scoped(_sa.select(AiKnowledgeSource).where(where), AiKnowledgeSource, tenant)
            .order_by(AiKnowledgeSource.created_at.desc(), AiKnowledgeSource.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    return [_source_out(r) for r in rows], total or 0


async def delete_source(session: AsyncSession, user: _t.Any, source_id: _uuid.UUID) -> None:
    tenant = _gateway.tenant_of(user)
    stmt = _scoped(_sa.select(AiKnowledgeSource).where(AiKnowledgeSource.id == source_id, _visibility(user)), AiKnowledgeSource, tenant)
    source = (await session.execute(stmt)).scalar_one_or_none()
    if source is None:
        raise AppError("not_found", "source not found", 404)
    if source.owner_id != user.id and not _gateway.has_role(user, _config.MANAGE_ROLES):
        raise AppError("forbidden", "only the owner or a manager can delete a source", 403)
    await session.delete(source)
    await session.commit()


_SEARCH_SQL = f"""
SELECT c.id AS chunk_id, c.source_id, s.title, c.text, c.position,
       LEAST(10000, ROUND(10000 * (0.6 * ts_rank(c.tsv, q.tsq, 32) + 0.4 * GREATEST(cos.v, 0))))::int AS score_bp
FROM ai_knowledge_chunks c
JOIN ai_knowledge_sources s ON s.id = c.source_id
CROSS JOIN (SELECT to_tsquery('simple', :tsq) AS tsq) q
CROSS JOIN LATERAL (
    SELECT CASE WHEN c.emb_norm2 = 0 OR CAST(:qnorm2 AS bigint) = 0 THEN 0.0
                ELSE SUM(t.a * t.b)::float8 / sqrt(c.emb_norm2::float8 * CAST(CAST(:qnorm2 AS bigint) AS float8)) END AS v
    FROM unnest(c.embedding, CAST(:qvec AS integer[])) AS t(a, b)
) cos
WHERE {_VISIBLE_SQL}
  __TENANT__
  AND (c.tsv @@ q.tsq OR cos.v >= CAST(:min_cos AS float8))
ORDER BY score_bp DESC, s.created_at, c.position, c.id
LIMIT :limit
"""


async def search(session: AsyncSession, user: _t.Any, query: str, limit: int) -> list[_s.HitOut]:
    """Permitted chunks only, best first. The visibility condition is in the WHERE clause, ahead of ORDER BY and LIMIT."""
    tenant = _gateway.tenant_of(user)
    words = _words(query)[:24]
    if not words:
        return []
    vector = EMBEDDER.embed(query)
    params: dict[str, _t.Any] = {
        "tsq": " | ".join(dict.fromkeys(words)),
        "qvec": vector,
        "qnorm2": sum(v * v for v in vector),
        "uid": user.id,
        "roles": sorted(effective_roles(user.roles)),
        "min_cos": MIN_COSINE,
        "limit": limit,
    }
    tenant_sql = ""
    if tenant is not None:
        tenant_sql = "AND s.tenant_id = :tenant AND c.tenant_id = :tenant"
        params["tenant"] = tenant
    rows = (await session.execute(_sa.text(_SEARCH_SQL.replace("__TENANT__", tenant_sql)), params)).all()
    await session.commit()
    return [
        _s.HitOut(source_id=r.source_id, chunk_id=r.chunk_id, title=r.title, text=r.text, position=r.position, score_bp=r.score_bp)
        for r in rows
    ]


async def ask(session: AsyncSession, user: _t.Any, body: _s.AskIn) -> _s.AskOut:
    _gateway.require_call_role(user)  # asking spends gateway budget: same gate as /ai/complete (403 forbidden)
    hits = await search(session, user, body.question, body.limit)
    if not hits:  # nothing the caller may see matches: the model is not called at all
        return _s.AskOut(answer="", grounded=False, citations=[], call_id=None)
    messages = [
        _gw.Message(
            role="system",
            content="Answer the question using ONLY the numbered context passages. If they do not contain the answer, say so.",
        )
    ]
    for number, hit in enumerate(hits, 1):
        messages.append(_gw.Message(role="user", content=f"[{number}] {hit.title}\n{hit.text}"[:20_000]))
    messages.append(_gw.Message(role="user", content=f"Question: {body.question}"))
    # retain=False: the prompt holds permission-filtered chunks, so the call ledger keeps only hash and counts
    result = await _gateway.complete(session, user, _gw.CompleteIn(stage=_config.STAGE, messages=messages), retain=False)
    return _s.AskOut(
        answer=result.output_text or "",
        grounded=True,
        citations=[
            _s.CitationOut(source_id=h.source_id, chunk_id=h.chunk_id, title=h.title, quote=h.text[:QUOTE_CHARS], score_bp=h.score_bp)
            for h in hits
        ],
        call_id=result.call_id,
    )
