from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.main import app


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
        await connection.execute(text("TRUNCATE TABLE comments, posts, posts_tags, tags, users CASCADE"))


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
