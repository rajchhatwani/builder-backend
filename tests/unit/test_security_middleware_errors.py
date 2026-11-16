"""B1-005: oversize bodies, 500s and 413s keep the envelope and request-id/CORS/security headers."""

import pytest
from fastapi import FastAPI, Request
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from app.config import get_settings
from app.main import SecurityMiddleware

ORIGIN = "http://localhost:5173"


class _Body(BaseModel):
    name: str


def _client() -> TestClient:
    settings = get_settings().model_copy(update={"max_request_bytes": 1024 * 1024})
    app = FastAPI()

    @app.post("/raw")
    async def raw(request: Request) -> dict[str, int]:
        return {"n": len(await request.body())}

    @app.post("/model")
    async def model(body: _Body) -> dict[str, str]:
        return {"name": body.name}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        SecurityMiddleware, settings=settings.model_copy(update={"cors_origins": [ORIGIN]})
    )
    return TestClient(app, raise_server_exceptions=False)


def _chunks():
    for _ in range(3):
        yield b"x" * (512 * 1024)


@pytest.mark.parametrize("path", ["/raw", "/model"])
def test_chunked_oversize_is_413_with_headers(path: str) -> None:
    r = _client().post(path, content=_chunks(), headers={"Origin": ORIGIN})
    assert r.status_code == 413
    assert r.json()["code"] == "payload_too_large"
    assert r.headers["x-request-id"]
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert r.headers["x-content-type-options"] == "nosniff"


def test_declared_413_has_cors_and_security_headers() -> None:
    r = _client().post("/raw", content=b"x" * (2 * 1024 * 1024), headers={"Origin": ORIGIN})
    assert r.status_code == 413
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-request-id"]


def test_500_has_envelope_request_id_cors_and_security_headers() -> None:
    r = _client().get("/boom", headers={"Origin": ORIGIN})
    assert r.status_code == 500
    assert r.json()["code"] == "internal_error"
    assert r.headers["x-request-id"]
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert r.headers["x-content-type-options"] == "nosniff"


def test_500_is_logged_with_request_id() -> None:
    import structlog

    with structlog.testing.capture_logs() as logs:
        r = _client().get("/boom")
    events = [e for e in logs if e["event"] == "unhandled_exception"]
    assert events and events[0]["request_id"] == r.headers["x-request-id"]


def test_unicode_digit_content_length_does_not_crash() -> None:
    import asyncio

    settings = get_settings()
    seen: list[dict] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(m):
        seen.append(m)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/x",
        "headers": [(b"content-length", b"\xb2")],
    }
    asyncio.run(SecurityMiddleware(app, settings)(scope, receive, send))
    assert seen[0]["status"] == 200
