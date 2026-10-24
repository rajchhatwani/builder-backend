"""The real Alembic chain on a fresh database (the other tests build tables with create_all).

Covers what create_all cannot: upgrading a database that already holds projects, the append-only
trigger on the audit log, and a downgrade/upgrade round trip.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_HEAD = "d4f8b6c21a73"  # the revision before platform accounts


def _alembic(url: str, *args: str) -> None:
    env = {**os.environ, "BUILDER_DATABASE_URL": url, "SECRET_KEY": "migration-test-secret"}
    done = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, f"alembic {' '.join(args)} failed:\n{done.stdout}\n{done.stderr}"


@pytest.fixture
async def fresh_db(database_url: str) -> str:
    """An empty database on the test server, returned as an asyncpg-style SQLAlchemy URL."""
    plain = database_url.replace("postgresql+asyncpg://", "postgresql://")
    admin = await asyncpg.connect(plain)
    name = f"migr_{uuid.uuid4().hex[:8]}"
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    return database_url.rsplit("/", 1)[0] + "/" + name


async def _connect(url: str) -> asyncpg.Connection:
    return await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))


async def test_upgrade_over_existing_projects_keeps_them_unclaimed(fresh_db: str) -> None:
    _alembic(fresh_db, "upgrade", PREVIOUS_HEAD)
    conn = await _connect(fresh_db)
    try:
        await conn.execute(
            "INSERT INTO projects (id, name, slug, db_engine, version, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'Legacy', 'legacy', 'postgres', 1, now(), now())"
        )
    finally:
        await conn.close()

    _alembic(fresh_db, "upgrade", "head")

    conn = await _connect(fresh_db)
    try:
        assert await conn.fetchval("SELECT count(*) FROM projects") == 1
        assert (
            await conn.fetchval("SELECT count(*) FROM project_members") == 0
        )  # unclaimed, not lost
    finally:
        await conn.close()


async def test_email_must_be_lower_case_in_the_database(fresh_db: str) -> None:
    _alembic(fresh_db, "upgrade", "head")
    conn = await _connect(fresh_db)
    try:
        insert = (
            "INSERT INTO platform_users (id, email, name, password_hash, status, platform_role, "
            "token_version, failed_logins, password_changed_at, must_change_password, "
            "created_at, updated_at) VALUES (gen_random_uuid(), $1, '', 'x', 'active', "
            "'customer', 0, 0, now(), false, now(), now())"
        )
        await conn.execute(insert, "ok@example.com")
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(insert, "Mixed@Example.com")
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(insert, "ok@example.com")
    finally:
        await conn.close()


async def test_audit_log_is_append_only(fresh_db: str) -> None:
    _alembic(fresh_db, "upgrade", "head")
    conn = await _connect(fresh_db)
    try:
        await conn.execute(
            "INSERT INTO platform_audit_log (at, via, action, result) "
            "VALUES (now(), 'session', 'x', 'ok')"
        )
        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            await conn.execute("UPDATE platform_audit_log SET action = 'tampered'")
        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            await conn.execute("DELETE FROM platform_audit_log")
        assert await conn.fetchval("SELECT action FROM platform_audit_log") == "x"
    finally:
        await conn.close()


async def test_downgrade_and_upgrade_round_trip(fresh_db: str) -> None:
    _alembic(fresh_db, "upgrade", "head")
    _alembic(fresh_db, "downgrade", PREVIOUS_HEAD)
    conn = await _connect(fresh_db)
    try:
        tables = {
            r[0]
            for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        }
        assert "platform_users" not in tables and "projects" in tables
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM pg_proc WHERE proname='platform_audit_log_immutable'"
            )
            == 0
        )
    finally:
        await conn.close()
    _alembic(fresh_db, "upgrade", "head")
