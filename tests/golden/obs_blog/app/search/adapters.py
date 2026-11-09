"""Search engines. An engine only ever returns ranked candidate ids: the rows themselves are always
re-read from Postgres through the caller's access scope (app/search/service.py), so a stale or
tampered index can never show a row the caller may not list.

Documents hold only the entity's `searchable` field values (as text), nothing else.
"""

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from typing import Protocol

import structlog

from app.search import config

logger = structlog.get_logger()


class SearchUnavailable(Exception):
    """The engine could not answer. The request fails (503); it is never answered by another engine."""


class SearchAdapter(Protocol):
    async def index(self, entity: str, doc_id: str, doc: dict[str, str]) -> None: ...

    async def delete(self, entity: str, doc_id: str) -> None: ...

    async def query_ids(self, entity: str, q: str, fields: tuple[str, ...], limit: int) -> list[str]: ...


_WORD = re.compile(r"\w+")


class FakeAdapter:
    """In-memory engine for tests (backend `opensearch-fake`). Word match on the requested fields only."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, dict[str, str]]] = {}

    async def index(self, entity: str, doc_id: str, doc: dict[str, str]) -> None:
        self.docs.setdefault(entity, {})[doc_id] = dict(doc)

    async def delete(self, entity: str, doc_id: str) -> None:
        self.docs.get(entity, {}).pop(doc_id, None)

    async def query_ids(self, entity: str, q: str, fields: tuple[str, ...], limit: int) -> list[str]:
        terms = [t.lower() for t in _WORD.findall(q)]
        if not terms:
            return []
        scored: list[tuple[int, str]] = []
        for doc_id, doc in self.docs.get(entity, {}).items():
            words = [w.lower() for name in fields for w in _WORD.findall(doc.get(name, ""))]
            if all(t in words for t in terms):
                scored.append((-sum(words.count(t) for t in terms), doc_id))
        return [doc_id for _score, doc_id in sorted(scored)[:limit]]


class OpenSearchAdapter:
    """OpenSearch over HTTP (stdlib urllib in a worker thread). The optional credential comes from
    SEARCH_OPENSEARCH_API_KEY and is sent as `Authorization: ApiKey ...`; it is never logged."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.prefix = os.environ.get("SEARCH_OPENSEARCH_INDEX_PREFIX", "app-")
        self.timeout = float(os.environ.get("SEARCH_OPENSEARCH_TIMEOUT", "5"))

    def _index(self, entity: str) -> str:
        return self.prefix + re.sub(r"[^a-z0-9_-]", "-", entity.lower())

    def _call(self, method: str, path: str, body: dict[str, object] | None) -> dict[str, object] | None:
        request = urllib.request.Request(  # noqa: S310 - scheme checked at startup (http/https)
            self.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        key = os.environ.get("SEARCH_OPENSEARCH_API_KEY")
        if key:
            request.add_header("Authorization", f"ApiKey {key}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise SearchUnavailable(f"opensearch answered {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SearchUnavailable("opensearch is not reachable") from None
        parsed = json.loads(raw) if raw else {}
        return parsed if isinstance(parsed, dict) else {}

    async def index(self, entity: str, doc_id: str, doc: dict[str, str]) -> None:
        await asyncio.to_thread(self._call, "PUT", f"/{self._index(entity)}/_doc/{doc_id}", dict(doc))

    async def delete(self, entity: str, doc_id: str) -> None:
        await asyncio.to_thread(self._call, "DELETE", f"/{self._index(entity)}/_doc/{doc_id}", None)

    async def query_ids(self, entity: str, q: str, fields: tuple[str, ...], limit: int) -> list[str]:
        body: dict[str, object] = {
            "size": limit,
            "_source": False,
            "query": {"multi_match": {"query": q, "fields": list(fields), "operator": "and"}},
        }
        found = await asyncio.to_thread(self._call, "POST", f"/{self._index(entity)}/_search", body)
        hits = (found or {}).get("hits")
        rows = hits.get("hits") if isinstance(hits, dict) else None
        return [str(h["_id"]) for h in rows if isinstance(h, dict) and "_id" in h] if isinstance(rows, list) else []


_fake = FakeAdapter()
_real: dict[str, OpenSearchAdapter] = {}


def fake_engine() -> FakeAdapter:
    """The one in-memory engine (tests inspect and clear it)."""
    return _fake


def get_adapter() -> SearchAdapter | None:
    """The engine for the configured backend; None for fts (nothing to keep in sync)."""
    name = config.backend()
    if name == config.FTS:
        return None
    if name == config.FAKE:
        return _fake
    url = config.opensearch_url()
    if not url:
        raise SearchUnavailable("SEARCH_OPENSEARCH_URL is not set")
    if url not in _real:
        _real[url] = OpenSearchAdapter(url)
    return _real[url]
