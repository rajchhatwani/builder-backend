"""The provider lock (generated): a database remembers which identity provider it was started
with, and an app built for a different one refuses to start on it."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select

from app.auth import config
from app.auth.models import AuthProviderLock
from app.auth.provider_lock import ProviderMismatchError, ensure_provider_lock
from app.db import session_factory

pytestmark = pytest.mark.usefixtures("outbox")


async def _clear() -> None:
    async with session_factory() as session:
        await session.execute(delete(AuthProviderLock))
        await session.commit()


async def _row() -> AuthProviderLock | None:
    async with session_factory() as session:
        return (await session.execute(select(AuthProviderLock))).scalar_one_or_none()


@pytest.fixture(autouse=True)
async def empty_lock() -> AsyncIterator[None]:
    await _clear()
    yield
    await _clear()


async def test_the_first_start_records_the_provider() -> None:
    await ensure_provider_lock()

    row = await _row()
    assert row is not None
    assert (row.provider, row.realm) == (config.PROVIDER, config.PROVIDER_REALM)


async def test_starting_again_with_the_same_provider_is_fine() -> None:
    await ensure_provider_lock()
    await ensure_provider_lock()


async def test_a_different_provider_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    await ensure_provider_lock()
    monkeypatch.setattr(config, "PROVIDER", "somewhere-else")

    with pytest.raises(ProviderMismatchError, match="AUTH_ALLOW_PROVIDER_SWITCH"):
        await ensure_provider_lock()

    row = await _row()
    assert row is not None and row.provider != "somewhere-else"


async def test_a_different_realm_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    await ensure_provider_lock()
    monkeypatch.setattr(config, "PROVIDER_REALM", "another-realm")

    with pytest.raises(ProviderMismatchError):
        await ensure_provider_lock()


async def test_switching_can_be_allowed_on_purpose(monkeypatch: pytest.MonkeyPatch) -> None:
    await ensure_provider_lock()
    monkeypatch.setattr(config, "PROVIDER", "somewhere-else")
    monkeypatch.setenv("AUTH_ALLOW_PROVIDER_SWITCH", "true")
    config.get_auth_settings.cache_clear()
    try:
        await ensure_provider_lock()
    finally:
        config.get_auth_settings.cache_clear()

    row = await _row()
    assert row is not None and row.provider == "somewhere-else"
