"""F-008: browser preflight for the preview proxy must allow X-Preview-Token."""

from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_preflight_allows_preview_token_header() -> None:
    origins = get_settings().cors_origins
    assert origins and "*" not in origins
    client = TestClient(app)  # no context manager: skip the DB-bound lifespan
    resp = client.options(
        "/previews/some-id/",
        headers={
            "Origin": origins[0],
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Preview-Token",
        },
    )
    assert resp.status_code == 200
    allowed = resp.headers.get("access-control-allow-headers", "").lower()
    assert "x-preview-token" in allowed


def test_cors_middleware_present() -> None:
    assert any(m.cls is CORSMiddleware for m in app.user_middleware)
