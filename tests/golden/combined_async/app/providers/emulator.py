"""The test emulator: a deterministic in-process fake adapter for every kind (generated).

It records what was sent and fails on demand, so retry and circuit-breaker logic can be tested
without a network. It is the only adapter that runs when APP_ENV is not production and the tenant has
stored no credentials, so generated tests and development never reach out."""

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.providers.base import Credentials
from app.providers.errors import AuthFailed, Permanent, RateLimited, Retryable
from app.providers.schemas import HealthStatus, SendResult

FAILURES = ("retryable", "permanent", "auth", "rate_limit", "timeout")


@dataclass
class Sent:
    kind: str
    message_id: str
    request: dict[str, Any]


@dataclass
class EmulatorState:
    sent: dict[str, list[Sent]] = field(default_factory=lambda: defaultdict(list))
    calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    failures: dict[str, deque[tuple[str, float | None]]] = field(default_factory=lambda: defaultdict(deque))
    unhealthy: set[str] = field(default_factory=set)

    def reset(self) -> None:
        self.sent.clear()
        self.calls.clear()
        self.failures.clear()
        self.unhealthy.clear()

    def inject(self, kind: str, failure: str, times: int = 1, value: float | None = None) -> None:
        """The next `times` calls of `kind` fail. `value` is retry_after for rate_limit, or how long a
        timeout call hangs (default: an hour, i.e. until the client's timeout cancels it)."""
        if failure not in FAILURES:
            raise ValueError(f"failure must be one of {FAILURES}")
        for _ in range(times):
            self.failures[kind].append((failure, value))


STATE = EmulatorState()


class Emulator:
    name = "emulator"

    def __init__(self, kind: str) -> None:
        self.kind = kind

    async def health(self, credentials: Credentials | None) -> HealthStatus:
        if self.kind in STATE.unhealthy:
            return HealthStatus(ok=False, detail="emulator marked unhealthy")
        return HealthStatus(ok=True, detail="emulator")

    async def call(self, request: BaseModel, credentials: Credentials | None) -> BaseModel:
        STATE.calls[self.kind] += 1
        queue = STATE.failures[self.kind]
        if queue:
            failure, value = queue.popleft()
            if failure == "retryable":
                raise Retryable("emulator: injected retryable failure")
            if failure == "permanent":
                raise Permanent("emulator: injected permanent failure")
            if failure == "auth":
                raise AuthFailed("emulator: injected authentication failure")
            if failure == "rate_limit":
                raise RateLimited("emulator: injected rate limit", retry_after=value)
            await asyncio.sleep(value if value is not None else 3600.0)
        message_id = f"emu-{self.kind}-{len(STATE.sent[self.kind]) + 1:06d}"
        STATE.sent[self.kind].append(Sent(self.kind, message_id, request.model_dump()))
        return SendResult(message_id=message_id)
