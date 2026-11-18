"""Audit B1-006: releasing the cross-worker intake lock never raises and never pools a locked connection."""

import uuid
from typing import Any

import pytest

from app.services.requirements.service import RequirementsService


class _Conn:
    def __init__(self, fail: bool = False, got: bool | None = True) -> None:
        self.fail, self.got = fail, got
        self.invalidated = self.closed = False

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        if self.fail:
            raise RuntimeError("connection killed")
        got = self.got

        class _R:
            def scalar(self) -> Any:
                return got

        return _R()

    async def invalidate(self) -> None:
        self.invalidated = True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_unlock_failure_does_not_raise_and_invalidates() -> None:
    c = _Conn(fail=True)
    await RequirementsService._release_cross_worker(c, uuid.uuid4())
    assert c.invalidated and c.closed


@pytest.mark.asyncio
async def test_unlock_false_invalidates() -> None:
    c = _Conn(got=False)
    await RequirementsService._release_cross_worker(c, uuid.uuid4())
    assert c.invalidated and c.closed


@pytest.mark.asyncio
async def test_clean_unlock_keeps_connection() -> None:
    c = _Conn()
    await RequirementsService._release_cross_worker(c, uuid.uuid4())
    assert not c.invalidated and c.closed
