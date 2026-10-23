"""Creates the test database if it does not exist yet (run by `make test`)."""

import asyncio
import re

import asyncpg
from sqlalchemy.engine import make_url

from app.config import get_settings


async def main() -> None:
    url = make_url(get_settings().database_url)
    name = url.database or ""
    if not name.endswith("_test") or not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise SystemExit(f"refusing to prepare {name!r}: test database names must end with _test")
    admin_dsn = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    connection = await asyncpg.connect(admin_dsn)
    try:
        exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
