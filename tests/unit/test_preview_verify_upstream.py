"""S2-012: the proxy re-checks, before forwarding, that the stored app_ip is still the address of
the preview's OWN app container; a recycled subnet/IP fails closed."""

import uuid
from types import SimpleNamespace

import pytest

from app.api import previews as api
from app.exceptions import AppError
from app.services import preview_service as ps
from app.services.sandbox import SandboxError


class Box:
    def __init__(self, answer: str | None | Exception) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    async def ip_of(self, sid: str, net: str) -> str | None:
        self.calls.append((sid, net))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def preview(ip: str | None = "10.9.0.2") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), app_ip=ip, app_sandbox="a" * 16, db_sandbox="b" * 16)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    api._verified.clear()
    slept: list[uuid.UUID] = []

    async def sleep_preview(pid: uuid.UUID, error: str | None = None) -> bool:
        slept.append(pid)
        return True

    monkeypatch.setattr(ps, "sleep_preview", sleep_preview)
    return slept


async def test_matching_owner_ip_passes_and_is_cached(_clean: list[uuid.UUID]) -> None:
    p, box = preview(), Box("10.9.0.2")
    await api.verify_upstream(box, p, now=100.0)  # type: ignore[arg-type]
    await api.verify_upstream(box, p, now=102.0)  # type: ignore[arg-type]
    assert box.calls == [("a" * 16, "bbsbx-" + "b" * 16)]  # asked the preview's own net, once
    await api.verify_upstream(box, p, now=100.0 + api.VERIFY_TTL_SECONDS + 1)  # type: ignore[arg-type]
    assert len(box.calls) == 2 and not _clean


@pytest.mark.parametrize("answer", [None, "10.9.0.7", SandboxError("runner down"), TimeoutError()])
async def test_recycled_or_unverifiable_address_fails_closed(
    answer: str | None | Exception, _clean: list[uuid.UUID]
) -> None:
    p = preview()
    with pytest.raises(AppError) as ei:
        await api.verify_upstream(Box(answer), p, now=1.0)  # type: ignore[arg-type]
    assert ei.value.status_code == 502 and ei.value.code == "preview_unverified"
    assert _clean == [p.id]  # healed: stack torn down, next request wakes a fresh one
    assert p.id not in api._verified


async def test_cache_never_outlives_an_address_change() -> None:
    p, box = preview("10.9.0.2"), Box("10.9.0.2")
    await api.verify_upstream(box, p, now=1.0)  # type: ignore[arg-type]
    p.app_ip = "10.9.0.9"  # woke with a new address; the stale cache entry must not apply
    with pytest.raises(AppError):
        await api.verify_upstream(box, p, now=2.0)  # type: ignore[arg-type]


async def test_missing_ip_is_refused() -> None:
    with pytest.raises(AppError):
        await api.verify_upstream(Box(None), preview(None), now=1.0)  # type: ignore[arg-type]
