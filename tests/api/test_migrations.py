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
        # ...and parked in the holding org, because organization_id is NOT NULL now (§3.2).
        assert (
            await conn.fetchval(
                "SELECT o.slug FROM projects p JOIN organizations o ON o.id = p.organization_id"
            )
            == "unclaimed-projects"
        )
        nullable = await conn.fetchval(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'projects' AND column_name = 'organization_id'"
        )
        assert nullable == "NO"
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


async def test_sso_tables_and_constraints(fresh_db: str) -> None:
    """Phase D.1: §3.1 `sso_connections` / `sso_domains`, plus the login-state table."""
    _alembic(fresh_db, "upgrade", "head")
    conn = await _connect(fresh_db)
    try:
        tables = {
            r[0]
            for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        }
        assert {"sso_connections", "sso_domains", "sso_login_requests"} <= tables
        org = await conn.fetchval(
            "INSERT INTO organizations (id, name, slug, kind, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'Acme', 'acme', 'team', now(), now()) RETURNING id"
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO sso_domains (domain, organization_id, dns_token) VALUES ($1, $2, 't')",
                "Acme.com",
                org,
            )
        insert = (
            "INSERT INTO sso_connections (id, organization_id, protocol, jit_role) "
            "VALUES (gen_random_uuid(), $1, $2, $3)"
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(insert, org, "saml", "owner")  # JIT never makes owners
        await conn.execute(insert, org, "saml", "member")
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(insert, org, "oidc", "member")  # one connection per org
        assert await conn.fetchval("SELECT active FROM sso_connections") is False
    finally:
        await conn.close()
    _alembic(fresh_db, "downgrade", "d8f2a4b6c1e3")
    _alembic(fresh_db, "upgrade", "head")


async def test_mfa_and_security_policy_columns(fresh_db: str) -> None:
    """Row 6: built-in TOTP (§4.4), org security policies (§8), SSO test results (§12.D.5–6)."""
    _alembic(fresh_db, "upgrade", "head")
    conn = await _connect(fresh_db)
    try:
        tables = {
            r[0]
            for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        }
        assert "mfa_recovery_codes" in tables

        async def columns(table: str) -> set[str]:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name=$1", table
            )
            return {r[0] for r in rows}

        assert {"totp_secret_enc", "totp_enabled_at", "totp_last_step"} <= await columns(
            "platform_users"
        )
        assert {"auth_methods", "family_started_at"} <= await columns("platform_refresh_tokens")
        assert {"require_mfa", "session_ttl_hours"} <= await columns("organizations")
        assert {"purpose", "test_user_id"} <= await columns("sso_login_requests")
        assert {"last_test_at", "last_test_result", "last_tested_by"} <= await columns(
            "sso_connections"
        )
        org = await conn.fetchval(
            "INSERT INTO organizations (id, name, slug, kind, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'Acme', 'acme', 'team', now(), now()) RETURNING id"
        )
        assert await conn.fetchval("SELECT require_mfa FROM organizations") is False
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("UPDATE organizations SET session_ttl_hours = 0 WHERE id = $1", org)
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO sso_login_requests (id, organization_id, protocol, browser_hash, "
                "expires_at, purpose) VALUES ('x', $1, 'saml', 'h', now(), 'other')",
                org,
            )
    finally:
        await conn.close()
    _alembic(fresh_db, "downgrade", "e4b9c2d7a1f5")
    _alembic(fresh_db, "upgrade", "head")


async def test_scim_tables_and_constraints(fresh_db: str) -> None:
    """Phase E.1: §3.1 `scim_directories` plus the SCIM user/group resources."""
    _alembic(fresh_db, "upgrade", "head")
    conn = await _connect(fresh_db)
    try:
        tables = {
            r[0]
            for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        }
        assert {"scim_directories", "scim_users", "scim_groups", "scim_group_members"} <= tables
        org = await conn.fetchval(
            "INSERT INTO organizations (id, name, slug, kind, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'Acme', 'acme', 'team', now(), now()) RETURNING id"
        )
        user = await conn.fetchval(
            "INSERT INTO platform_users (id, email, name, password_hash, status, platform_role, "
            "token_version, failed_logins, password_changed_at, must_change_password, "
            "created_at, updated_at) VALUES (gen_random_uuid(), 'a@acme.test', 'A', '!sso-only', "
            "'active', 'customer', 0, 0, now(), false, now(), now()) RETURNING id"
        )
        await conn.execute(
            "INSERT INTO scim_directories (organization_id, bearer_hash) VALUES ($1, 'h')", org
        )
        assert await conn.fetchval("SELECT active FROM scim_directories") is False
        assert await conn.fetchval("SELECT group_roles::text FROM scim_directories") == "{}"
        insert = (
            "INSERT INTO scim_users (id, organization_id, user_id, user_name) "
            "VALUES (gen_random_uuid(), $1, $2, $3)"
        )
        await conn.execute(insert, org, user, "A@acme.test")
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(insert, org, user, "other@acme.test")  # one per account per org
        g = "INSERT INTO scim_groups (id, organization_id, display_name) VALUES (gen_random_uuid(), $1, $2)"
        await conn.execute(g, org, "Owners")
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(g, org, "owners")  # names are case-insensitive
    finally:
        await conn.close()
    _alembic(fresh_db, "downgrade", "f5c3a8e1b7d9")
    _alembic(fresh_db, "upgrade", "head")


async def test_backfill_puts_project_members_into_the_projects_org(fresh_db: str) -> None:
    """Review F-012 (plan §3.2): a legacy project member who sits in no org gets a seat in the
    project's org; existing org members keep their role; running it twice changes nothing."""
    _alembic(fresh_db, "upgrade", "b3d7f1a9c5e2")
    conn = await _connect(fresh_db)
    try:
        user_sql = (
            "INSERT INTO platform_users (id, email, name, password_hash, status, platform_role, "
            "token_version, failed_logins, password_changed_at, must_change_password, "
            "created_at, updated_at) VALUES (gen_random_uuid(), $1, 'T', 'x', 'active', "
            "'customer', 0, 0, now(), false, now(), now()) RETURNING id"
        )
        owner = await conn.fetchval(user_sql, "owner@legacy.test")
        editor = await conn.fetchval(user_sql, "editor@legacy.test")
        admin = await conn.fetchval(user_sql, "admin@legacy.test")
        org = await conn.fetchval(
            "INSERT INTO organizations (id, name, slug, kind, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'Owner', 'owner-personal', 'personal', now(), now()) "
            "RETURNING id"
        )
        member_sql = (
            "INSERT INTO organization_members (organization_id, user_id, role, joined_at) "
            "VALUES ($1, $2, $3, now())"
        )
        await conn.execute(member_sql, org, owner, "owner")
        await conn.execute(member_sql, org, admin, "admin")  # already in: must stay admin
        project = await conn.fetchval(
            "INSERT INTO projects (id, name, slug, db_engine, version, organization_id, "
            "created_at, updated_at) VALUES (gen_random_uuid(), 'P', 'p', 'postgres', 1, $1, "
            "now(), now()) RETURNING id",
            org,
        )
        pm_sql = (
            "INSERT INTO project_members (project_id, user_id, role, created_at) "
            "VALUES ($1, $2, $3, now())"
        )
        await conn.execute(pm_sql, project, owner, "owner")
        await conn.execute(pm_sql, project, editor, "editor")
        await conn.execute(pm_sql, project, admin, "viewer")
    finally:
        await conn.close()

    _alembic(fresh_db, "upgrade", "head")
    _alembic(fresh_db, "downgrade", "-1")
    _alembic(fresh_db, "upgrade", "head")  # idempotent

    conn = await _connect(fresh_db)
    try:
        rows = {
            r["email"]: r["role"]
            for r in await conn.fetch(
                "SELECT u.email, om.role FROM organization_members om "
                "JOIN platform_users u ON u.id = om.user_id"
            )
        }
        assert rows == {
            "owner@legacy.test": "owner",
            "admin@legacy.test": "admin",
            "editor@legacy.test": "member",
        }
        assert await conn.fetchval("SELECT count(*) FROM project_members") == 3
    finally:
        await conn.close()


async def test_phase_f_impersonation_columns_and_rls_policies_are_installed_but_off(
    fresh_db: str,
) -> None:
    """Phase F: consent defaults to on, the session table exists, the audit `via` fits
    "impersonation", and the RLS policies exist on every org-scoped table without RLS being
    enabled anywhere."""
    from app.core import rls

    _alembic(fresh_db, "upgrade", "head")
    conn = await _connect(fresh_db)
    try:
        default = await conn.fetchval(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'organizations' AND column_name = 'allow_impersonation'"
        )
        assert default == "true"
        assert await conn.fetchval("SELECT to_regclass('impersonation_sessions')") is not None
        width = await conn.fetchval(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'platform_audit_log' AND column_name = 'via'"
        )
        assert width == 20
        policies = {
            r["tablename"]
            for r in await conn.fetch(
                "SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'"
            )
        }
        assert policies == set(rls.ALL_TABLES)
        on = await conn.fetch(
            "SELECT relname FROM pg_class WHERE relrowsecurity OR relforcerowsecurity"
        )
        assert on == []  # nothing is switched on by a migration
    finally:
        await conn.close()
    _alembic(fresh_db, "downgrade", "d1f5a7c3e9b2")
    _alembic(fresh_db, "upgrade", "head")


async def test_project_slug_per_org_migration_is_reversible_on_populated_data(
    fresh_db: str,
) -> None:
    """FEAT F-2: two orgs share a slug after the upgrade; downgrade must dedupe, not fail."""
    _alembic(fresh_db, "upgrade", "head")
    conn = await _connect(fresh_db)
    try:
        orgs = []
        for slug in ("org-a", "org-b"):
            orgs.append(
                await conn.fetchval(
                    "INSERT INTO organizations (id, name, slug, kind, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), $1, $1, 'team', now(), now()) RETURNING id",
                    slug,
                )
            )
        for org in orgs:
            await conn.execute(
                "INSERT INTO projects (id, name, slug, db_engine, version, organization_id, "
                "created_at, updated_at) VALUES (gen_random_uuid(), 'Blog', 'blog', 'postgres', "
                "1, $1, now(), now())",
                org,
            )
        with_dupe = await conn.fetchval("SELECT count(*) FROM projects WHERE slug='blog'")
        assert with_dupe == 2
    finally:
        await conn.close()
    _alembic(fresh_db, "downgrade", "f2c8a4e6b1d9")
    conn = await _connect(fresh_db)
    try:
        slugs = [r[0] for r in await conn.fetch("SELECT slug FROM projects")]
        assert len(set(slugs)) == 2 and "blog" in slugs
    finally:
        await conn.close()
    _alembic(fresh_db, "upgrade", "head")
