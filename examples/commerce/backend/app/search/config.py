"""Which search engine answers GET /<entity>/search (read from the environment).

SEARCH_BACKEND = fts (default, Postgres full-text) | opensearch (SEARCH_OPENSEARCH_URL required)
                 | opensearch-fake (in-memory engine for tests only; refused when APP_ENV=production)
A misconfigured backend stops the app at startup. There is never a silent fallback to another engine.
"""

import os

FTS = "fts"
OPENSEARCH = "opensearch"
FAKE = "opensearch-fake"
BACKENDS = (FTS, OPENSEARCH, FAKE)


class SearchConfigError(RuntimeError):
    pass


def backend() -> str:
    return (os.environ.get("SEARCH_BACKEND") or FTS).strip().lower()


def opensearch_url() -> str:
    return (os.environ.get("SEARCH_OPENSEARCH_URL") or "").strip().rstrip("/")


def check_boot() -> None:
    """Refuse to start on an unknown backend, a missing OpenSearch URL, or the test engine in production."""
    name = backend()
    if name not in BACKENDS:
        raise SearchConfigError(f"SEARCH_BACKEND must be one of {', '.join(BACKENDS)} (got {name!r})")
    if name == OPENSEARCH:
        url = opensearch_url()
        if not url:
            raise SearchConfigError("SEARCH_BACKEND=opensearch needs SEARCH_OPENSEARCH_URL")
        if not url.startswith(("http://", "https://")):
            raise SearchConfigError("SEARCH_OPENSEARCH_URL must start with http:// or https://")
    if name == FAKE and os.environ.get("APP_ENV", "").strip().lower() == "production":
        raise SearchConfigError("SEARCH_BACKEND=opensearch-fake is for tests and is refused in production")
