import httpx
import pytest

from app.main import app


@pytest.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_reports_db_state(client: httpx.AsyncClient) -> None:
    # No assumption about a live DB here: either it's reachable (200) or the
    # structured error envelope correctly reports unavailability (503).
    response = await client.get("/ready")
    assert response.status_code in (200, 503)
    if response.status_code == 503:
        assert response.json()["code"] == "http_error"
