"""The resource budget of effectful hooks (generated, pure Python, no platform imports).

One `Ledger` per API process. `charge` is called before every outbound effect and raises
`OverBudget` (with a short code, never data) when the call would break a limit of the hook:

  not_declared  the effect type is not in the hook's `effects` list
  wall_clock    the hook has already run longer than its wall-clock limit
  payload       one call carries more bytes than `payload_bytes`
  calls         more calls of this effect type in one invocation than `calls_per_effect`
  rate          more outbound calls in the last 60 seconds than `outbound_per_minute`

The `rate` window is kept per TENANT (all hooks of one tenant share it; a hook compares the tenant's count
with its own `outbound_per_minute`), so one tenant cannot use up another's allowance and a second hook does
not give a tenant a second allowance. The window lives in this process. With N API replicas each process
enforces ceil(limit / N), where N is the `EFFECT_REPLICAS` environment variable (default 1, max 1000), so the
fleet-wide bound for one tenant is at most limit + N - 1 calls per minute. Set EFFECT_REPLICAS to the number
of API replicas; an unset or invalid value means 1 (the limit is then per process, up to limit x replicas).
"""

import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

WINDOW_SECONDS = 60.0
NO_TENANT = "-"


def replicas() -> int:
    try:
        return min(1000, max(1, int(os.environ.get("EFFECT_REPLICAS", "1"))))
    except ValueError:
        return 1


class OverBudget(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EffectLimits:
    effects: frozenset[str]
    wall_seconds: float
    calls_per_effect: int
    payload_bytes: int
    outbound_per_minute: int


class Ledger:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._sent: dict[str, deque[float]] = {}

    def charge(
        self, hook: str, limits: EffectLimits | None, calls: dict[str, int], effect: str, size: int, started: float,
        tenant: str = NO_TENANT,
    ) -> None:
        """Count one call of `effect` (payload `size` bytes) for an invocation that began at `started`.
        `calls` is that invocation's counter. Nothing is counted when the call is refused."""
        if limits is None or effect not in limits.effects:
            raise OverBudget("not_declared")
        now = self._clock()
        if now - started > limits.wall_seconds:
            raise OverBudget("wall_clock")
        if size > limits.payload_bytes:
            raise OverBudget("payload")
        if calls.get(effect, 0) + 1 > limits.calls_per_effect:
            raise OverBudget("calls")
        with self._lock:
            window = self._sent.setdefault(tenant or NO_TENANT, deque())
            while window and now - window[0] >= WINDOW_SECONDS:
                window.popleft()
            share = -(-limits.outbound_per_minute // replicas())  # ceil
            if len(window) >= share:
                raise OverBudget("rate")
            window.append(now)
        calls[effect] = calls.get(effect, 0) + 1


LEDGER = Ledger()
