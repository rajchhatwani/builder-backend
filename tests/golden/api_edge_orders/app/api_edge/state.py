"""What the edge knows about one request (generated). Created by the middleware, read by the guard."""

import dataclasses
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession


@dataclasses.dataclass(frozen=True)
class Replay:
    status: int
    headers: list[tuple[str, str]]
    body: bytes


@dataclasses.dataclass
class EdgeState:
    version: str | None = None
    headers: list[tuple[str, str]] = dataclasses.field(default_factory=list)  # added to the response
    key: str | None = None  # a valid Idempotency-Key was sent on a covered method
    request_hash: str | None = None
    session: AsyncSession | None = None  # the request's one transaction (owned by the middleware)
    claim_id: uuid.UUID | None = None
    commit: Callable[[], Awaitable[None]] | None = None  # the session's real commit
    replay: Replay | None = None
    # after_commit stages of this request, held back until the real commit (None: not deferring)
    after_commit: list[Callable[[], Awaitable[None]]] | None = None
    committed: bool = False

    def set_header(self, name: str, value: str) -> None:
        self.headers = [(n, v) for n, v in self.headers if n.lower() != name.lower()]
        self.headers.append((name, value))
