"""Sliding-window limiter, in process. Good enough to blunt guessing against one worker.

Limitation (MASTER_PLAN L5): the counters live in this process, so N workers allow N times the
limit. The per-account lockout in the database is the shared control; this is the cheap first gate.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable


class SlidingWindowLimiter:
    def __init__(
        self,
        attempts: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 50_000,
    ) -> None:
        self.attempts = attempts
        self.window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Record an attempt; False when `key` is over its limit (the attempt is not recorded)."""
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.attempts:
            return False
        hits.append(now)
        if len(self._hits) > self._max_keys:
            self._evict(now)
        return True

    def blocked(self, key: str) -> bool:
        """True when `key` is over its limit; records nothing."""
        hits = self._hits.get(key)
        if not hits:
            return False
        now = self._clock()
        while hits and now - hits[0] > self.window:
            hits.popleft()
        return len(hits) >= self.attempts

    def retry_after(self, key: str) -> int:
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(1, int(self.window - (self._clock() - hits[0])) + 1)

    def reset(self) -> None:
        self._hits.clear()

    def _evict(self, now: float) -> None:
        # Bound memory against a flood of distinct keys: drop windows that have fully expired.
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
            del self._hits[key]
