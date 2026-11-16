"""Audit B1-028: MCP get_openapi returns a real OpenAPI document (F-0854)."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.generator import engine
from app.services.mcp_service import McpService
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor
from tests.api.test_mcp import _principal, _set_owner_mcp

Factory = async_sessionmaker[AsyncSession]


async def test_mcp_get_openapi_returns_openapi_document(
    client_for: ClientFor, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-0854"""
    owner = await client_for("owner@example.com")
    pid = await make_project(owner)
    await _set_owner_mcp(session_factory, uuid.UUID(pid), owner.user.id, True)  # type: ignore[attr-defined]

    def boom(spec: object) -> dict[str, str]:
        raise AssertionError("generate must not run for get_openapi")

    monkeypatch.setattr(engine, "generate", boom)
    async with session_factory() as db:
        user = await db.merge(owner.user)  # type: ignore[attr-defined]
        out = await McpService(db).get_openapi(await _principal(user), uuid.UUID(pid))
    assert str(out["openapi"]).startswith("3.1")
    assert "message" not in out
    assert isinstance(out["paths"], dict) and isinstance(out["info"], dict)
