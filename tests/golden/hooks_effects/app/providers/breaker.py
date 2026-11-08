"""A circuit breaker per (tenant, kind, adapter) (generated).

closed -> (N consecutive failures) -> open -> (after `reset_seconds`) -> half-open: ONE probe is let
through; its success closes the breaker, its failure opens it again for another `reset_seconds`."""

import time
from collections.abc import Callable

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self, failures: int, reset_seconds: float, clock: Callable[[], float] | None = None
    ) -> None:
        self.failures = failures
        self.reset_seconds = reset_seconds
        self._clock = clock or (lambda: time.monotonic())  # looked up per call so tests can freeze time
        self._count = 0
        self._opened_at = 0.0
        self._state = CLOSED
        self._probing = False

    @property
    def state(self) -> str:
        if self._state == OPEN and self._clock() - self._opened_at >= self.reset_seconds:
            return HALF_OPEN
        return self._state

    def allow(self) -> bool:
        """May a call go out now? In half-open exactly one caller gets True until it reports back."""
        state = self.state
        if state == CLOSED:
            return True
        if state == HALF_OPEN and not self._probing:
            self._state = HALF_OPEN
            self._probing = True
            return True
        return False

    def success(self) -> None:
        self._count = 0
        self._state = CLOSED
        self._probing = False

    def failure(self) -> None:
        self._probing = False
        if self._state == HALF_OPEN or self.state == HALF_OPEN:
            self._open()
            return
        self._count += 1
        if self._count >= self.failures:
            self._open()

    def _open(self) -> None:
        self._state = OPEN
        self._opened_at = self._clock()
        self._count = 0


_BREAKERS: dict[tuple[str, str, str], CircuitBreaker] = {}


def breaker_for(
    tenant: str, kind: str, name: str, failures: int, reset_seconds: float
) -> CircuitBreaker:
    key = (tenant, kind, name)
    found = _BREAKERS.get(key)
    if found is None:
        found = _BREAKERS[key] = CircuitBreaker(failures, reset_seconds)
    return found


def reset_all() -> None:
    _BREAKERS.clear()
