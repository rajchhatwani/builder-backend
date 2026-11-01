"""The adapter contract (generated)."""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.providers.schemas import HealthStatus


class Credentials:
    """A tenant's decrypted credentials for one provider, for the duration of one call.

    `str()` / `repr()` show names only, so an accidental log or exception cannot print a value."""

    __slots__ = ("_values",)

    def __init__(self, values: dict[str, str]) -> None:
        self._values = dict(values)

    def get(self, key_name: str) -> str:
        try:
            return self._values[key_name]
        except KeyError:
            raise KeyError(key_name) from None

    def names(self) -> list[str]:
        return sorted(self._values)

    def __bool__(self) -> bool:
        return bool(self._values)

    def __repr__(self) -> str:
        return f"Credentials(names={self.names()!r}, values=<redacted>)"

    __str__ = __repr__

    def __reduce__(self) -> tuple[type, tuple[dict[str, str]]]:
        raise TypeError("credentials cannot be serialized")


@runtime_checkable
class ProviderAdapter(Protocol):
    """One provider behind one kind. Implementations map every failure onto app.providers.errors
    (Retryable / Permanent / AuthFailed / RateLimited) and never put a credential or a body in a message."""

    kind: str
    name: str

    async def health(self, credentials: Credentials | None) -> HealthStatus: ...

    async def call(self, request: BaseModel, credentials: Credentials | None) -> BaseModel: ...
