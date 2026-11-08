"""Per-client sliding-window rate limits for the auth endpoints.

The sign-in group counts failures only (FailureRateLimiter); registration and e-mail / SMS
requests count every call.

State is kept in process memory: with several workers or replicas each one counts on its own,
and behind a reverse proxy every client shares the proxy's address unless the server is
started with proxy headers enabled. Use an edge or Redis based limiter for a hard guarantee.
"""

import re
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator

from fastapi import Request

from app.core.errors import AppError

_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
_PERIOD_RE = re.compile(r"(\d*)(second|minute|hour|day)s?")
_LIMITERS: list["RateLimiter"] = []


def parse_limit(limit: str) -> tuple[int, int]:
    """'5/15minutes' -> (5 requests, 900 seconds); '10/hour' -> (10, 3600)."""
    count, _, period = limit.partition("/")
    match = _PERIOD_RE.fullmatch(period)
    if not count.isdigit() or match is None:
        raise ValueError(f"invalid rate limit {limit!r}")
    return int(count), int(match.group(1) or 1) * _UNIT_SECONDS[match.group(2)]


class RateLimiter:
    """FastAPI dependency: raises 429 once a client exceeds `limit` on this endpoint group."""

    def __init__(self, name: str, limit: str) -> None:
        self.name = name
        self.count, self.window = parse_limit(limit)
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        _LIMITERS.append(self)

    async def __call__(self, request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = self._hits[client]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.count:
            retry_after = max(1, int(self.window - (now - hits[0])))
            raise AppError(
                "rate_limited",
                f"too many requests; retry in {retry_after} seconds",
                429,
            )
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()


class FailureRateLimiter(RateLimiter):
    """Counts only requests the endpoint rejects with a client error (wrong password, bad or
    expired token, wrong code), so normal sign-ins and token refreshes never use up the budget.
    Once a client has `limit` failures inside the window every further call gets 429 until the
    oldest failure ages out."""

    async def __call__(self, request: Request) -> AsyncIterator[None]:  # type: ignore[override]
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = self._hits[client]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.count:
            retry_after = max(1, int(self.window - (now - hits[0])))
            raise AppError(
                "rate_limited",
                f"too many requests; retry in {retry_after} seconds",
                429,
            )
        try:
            yield
        except AppError as exc:
            if 400 <= exc.status_code < 500 and exc.status_code != 429:
                self._hits[client].append(time.monotonic())
            raise


def reset_all() -> None:
    """Forget every client (used by the tests)."""
    for limiter in _LIMITERS:
        limiter.reset()
