"""Scenario test for the generated `custom_fields` project (Contact with per-row custom fields). Copied
into the project's tests/ folder by tests/e2e/test_custom_fields_stack.py and run against a real Postgres.

Rules under test: rows are validated against the custom field definitions (422); promoting `score` with
the generated migration moves the three values into a typed integer column and removes the key from the
JSONB; the list endpoint keeps serving the rows; the downgrade puts the values back into the JSONB and
drops the column; promoting a required field fails loudly (and changes nothing) when a row lacks a value.
"""

import subprocess
import sys
import uuid
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import text

from app.db import engine

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "alembic" / "versions"


def alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, capture_output=True, text=True, timeout=300
    )


async def scores() -> dict[str, object]:
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT full_name, score FROM contacts ORDER BY full_name"))).all()
    return {r[0]: r[1] for r in rows}


async def keys() -> list[set[str]]:
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT full_name, custom_fields FROM contacts ORDER BY full_name"))).all()
    return [set(r[1]) for r in rows]


async def make(client: AsyncClient, name: str, score: int, **extra: object) -> dict[str, object]:
    body = {"full_name": name, "custom_fields": {"tier": "gold", "score": score, **extra}}
    response = await client.post("/contacts", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, object] = response.json()
    return created


async def test_rows_are_validated_against_the_definitions(client: AsyncClient) -> None:
    bad = [
        {"tier": "gold", "score": "7"},  # a string is not an int
        {"tier": "gold", "score": True},  # a bool is not an int
        {"tier": "platinum"},  # not in the enum
        {"tier": "gold", "unknown": 1},  # unknown key
        {"score": 1},  # required tier missing
        {"tier": "gold", "nickname": "x" * 41},  # over max_length
        {"tier": "gold", "birthday": "yesterday"},
    ]
    for custom in bad:
        response = await client.post("/contacts", json={"full_name": "A", "custom_fields": custom})
        assert response.status_code == 422, (custom, response.text)
    big = {"tier": "gold", **{f"k{i}": 1 for i in range(25)}}
    assert (await client.post("/contacts", json={"full_name": "A", "custom_fields": big})).status_code == 422
    good = await make(client, "Ada", 5, vip=True, birthday="2026-01-02", last_seen="2026-01-02T03:04:05")
    assert good["custom_fields"]["vip"] is True  # type: ignore[index]
    patched = await client.patch(f"/contacts/{good['id']}", json={"custom_fields": {"tier": "silver"}})
    assert patched.status_code == 200 and patched.json()["custom_fields"] == {"tier": "silver"}
    assert (await client.patch(f"/contacts/{good['id']}", json={"custom_fields": None})).status_code == 422


async def test_promote_moves_the_data_and_the_downgrade_moves_it_back(client: AsyncClient) -> None:
    for name, score in (("A", 10), ("B", 20), ("C", 30)):
        await make(client, name, score)
    migration = VERSIONS / "0002_promote_score.py"
    migration.write_text((ROOT / "tests" / "promote_score.txt").read_text(encoding="utf-8"), encoding="utf-8")
    try:
        up = alembic("upgrade", "head")
        assert up.returncode == 0, up.stdout + up.stderr
        assert await scores() == {"A": 10, "B": 20, "C": 30}
        assert all("score" not in k for k in await keys())
        listing = await client.get("/contacts")
        assert listing.status_code == 200 and listing.json()["total"] == 3
        assert all(item["custom_fields"] == {"tier": "gold"} for item in listing.json()["items"])

        down = alembic("downgrade", "-1")
        assert down.returncode == 0, down.stdout + down.stderr
        async with engine.connect() as conn:
            columns = {r[0] for r in await conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'contacts'"))}
        assert "score" not in columns
        items = sorted((await client.get("/contacts")).json()["items"], key=lambda i: i["full_name"])
        assert [i["custom_fields"]["score"] for i in items] == [10, 20, 30]
    finally:
        migration.unlink(missing_ok=True)


async def test_required_promotion_fails_loudly_when_a_row_has_no_value(client: AsyncClient) -> None:
    await make(client, "A", 1)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO contacts (id, full_name, created_at, updated_at) VALUES (:i, 'NoTier', now(), now())"),
            {"i": uuid.uuid4()},
        )
    migration = VERSIONS / "0002_promote_tier.py"
    migration.write_text((ROOT / "tests" / "promote_tier.txt").read_text(encoding="utf-8"), encoding="utf-8")
    try:
        up = alembic("upgrade", "head")
        assert up.returncode != 0 and "no value" in up.stdout + up.stderr
        async with engine.connect() as conn:  # transactional DDL: nothing was changed
            columns = {r[0] for r in await conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'contacts'"))}
        assert "tier" not in columns
        assert alembic("current").returncode == 0
    finally:
        migration.unlink(missing_ok=True)
