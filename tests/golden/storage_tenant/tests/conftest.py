from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.main import app
from tests._auth_support import authed_client, outbox  # noqa: F401
from tests.storage_support import fake_clamd, fake_clamd_server, storage_env  # noqa: F401


@pytest.fixture(scope="session", autouse=True)
def _require_test_database() -> None:
    name = get_settings().database_url.rsplit("/", 1)[-1].split("?")[0]
    if not name.endswith("_test"):
        pytest.exit(
            f"Refusing to run: the tests empty every table but DATABASE_URL points at {name!r}. "
            "Use `make test` (the database name must end with _test).",
            returncode=2,
        )


@pytest.fixture(autouse=True)
async def _clean_database(_require_test_database: None) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE auth_invitations, auth_refresh_tokens, auth_tenants, auth_users, auth_verification_codes, photos, stor_files CASCADE"))


@pytest.fixture(autouse=True)
def _uploads_work(request: pytest.FixtureRequest) -> None:
    """Entities here have file fields, so many tests upload a file first: they get the stand-in
    scanner and an in-memory bucket, like the file tests do."""
    request.getfixturevalue("storage_env")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
