"""Fixtures for tests that send through a provider (generated). Import what you need:

    from tests._providers_support import emulator

The `emulator` fixture makes the in-process fake the only provider, records what is sent
(`emulator.sent["email"]`) and fails on demand (`emulator.inject("email", "retryable", times=2)`)."""

from collections.abc import Iterator

import pytest

from app.providers import breaker, client
from app.providers.emulator import STATE, EmulatorState

# Test-only master keys (never used outside the tests).
KEY_1 = "k1-4f9a7c2e81b36d05a9c4e7f2b8d1630a"
KEY_2 = "k2-b1e7094d3a6c58f2e0917ac4d5b83f26"


@pytest.fixture
def vault_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """APP_ENV=test and a test master key (version 1)."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("PROVIDER_VAULT_KEY", KEY_1)
    monkeypatch.setenv("PROVIDER_VAULT_KEY_VERSION", "1")
    monkeypatch.delenv("PROVIDER_VAULT_KEY_PREVIOUS", raising=False)
    return monkeypatch


@pytest.fixture
def emulator(vault_env: pytest.MonkeyPatch) -> Iterator[EmulatorState]:
    """The emulator is the only provider; no waiting between retries; breakers start closed."""
    STATE.reset()
    breaker.reset_all()
    waits: list[float] = []

    async def no_wait(seconds: float) -> None:
        waits.append(seconds)

    vault_env.setattr(client, "sleep", no_wait)
    STATE.waits = waits  # type: ignore[attr-defined]
    yield STATE
    STATE.reset()
    breaker.reset_all()
