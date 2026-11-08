"""SEC H-1: /mcp must accept the configured public hostname and still refuse unknown Hosts."""

from __future__ import annotations

import httpx
import pytest

from app.api.mcp import build_mcp_app
from app.config import Settings


async def _post(app: object, host: str) -> int:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with httpx.AsyncClient(transport=transport, base_url=f"http://{host}") as c:
            r = await c.post(
                "/",
                json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                headers={"Accept": "application/json, text/event-stream"},
            )
    return r.status_code


@pytest.mark.parametrize("host", ["api.example.com", "api.example.com:8443", "extra.example.org"])
async def test_configured_public_host_is_not_rejected(host: str) -> None:
    s = Settings(public_api_url="https://api.example.com", mcp_allowed_hosts=["extra.example.org"])
    assert await _post(build_mcp_app(None, s), host) != 421


@pytest.mark.parametrize("host", ["evil.example.net", "api.example.com.evil.net"])
async def test_unlisted_host_is_still_rejected(host: str) -> None:
    s = Settings(public_api_url="https://api.example.com")
    assert await _post(build_mcp_app(None, s), host) == 421


async def test_localhost_still_allowed() -> None:
    s = Settings(public_api_url="https://api.example.com")
    assert await _post(build_mcp_app(None, s), "127.0.0.1:8000") != 421
