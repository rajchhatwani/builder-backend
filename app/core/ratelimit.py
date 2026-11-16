"""Sliding-window limiter, in process. Good enough to blunt guessing against one worker.

Limitation (MASTER_PLAN L5): the counters live in this process, so N workers allow N times the
limit. The per-account lockout in the database is the shared control; this is the cheap first gate.
"""

import time
from collections import OrderedDict, deque
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
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()  # least recently used first

    def allow(self, key: str) -> bool:
        """Record an attempt; False when `key` is over its limit (the attempt is not recorded)."""
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            hits = self._hits[key] = deque()
        else:
            self._hits.move_to_end(key)
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.attempts:
            return False
        hits.append(now)
        while len(self._hits) > self._max_keys:
            self._hits.popitem(last=False)  # hard cap, O(1): drop the least recently used key
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
