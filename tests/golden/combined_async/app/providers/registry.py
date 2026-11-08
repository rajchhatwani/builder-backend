"""The adapter registry, keyed by (kind, name) (generated).

The `emulator` of every kind is registered here. Your own adapters are registered in
app/hooks/providers.py, which is imported once, the first time the registry is used."""

import importlib
from collections.abc import Callable

from app.providers import definitions
from app.providers.base import ProviderAdapter
from app.providers.emulator import Emulator
from app.providers.errors import NotConfigured
from app.providers.schemas import KINDS

_FACTORIES: dict[tuple[str, str], Callable[[], ProviderAdapter]] = {}
_loaded = False


def register(kind: str, name: str, factory: Callable[[], ProviderAdapter]) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if name == "emulator":
        raise ValueError("the name 'emulator' is reserved")
    _FACTORIES[(kind, name)] = factory


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for kind in KINDS:
        _FACTORIES[(kind, "emulator")] = lambda kind=kind: Emulator(kind)  # type: ignore[misc]
    importlib.import_module("app.hooks.providers")


def adapter(kind: str, name: str) -> ProviderAdapter:
    _load()
    factory = _FACTORIES.get((kind, name))
    if factory is None:
        raise NotConfigured("no adapter is registered for this provider")
    return factory()


def registered(kind: str) -> list[str]:
    _load()
    return sorted(n for (k, n) in _FACTORIES if k == kind)


def allowed(kind: str) -> list[str]:
    """The adapters the spec lets tenants select for `kind`, in spec order."""
    return list(definitions.ADAPTERS.get(kind, []))
