"""Postgres row-level security as a second wall behind the service-layer org checks (§3.3, §9).

Three separate switches, so nothing changes by accident:

1. `install_statements()` creates the policies. They are inert until a table has RLS enabled
   (the Alembic migration `f2c8a4e6b1d9` runs these).
2. `enable_statements()` turns RLS on (`ENABLE` + `FORCE`, so the table owner is bound too).
   Only `python -m app.core.rls enable --yes` does it; nothing in the app calls it.
3. `BUILDER_RLS_ENABLED` makes every org-scoped request bind `app.organization_id` for the
   transaction (`set_config(..., true)` = `SET LOCAL`, so a pooled connection never carries it
   to the next request). With RLS not enabled on the tables this changes nothing visible.

The policies confine a transaction to one org only when `app.organization_id` is set; unset
means "not an org-scoped request" (sign-in, webhooks, the operator console, background jobs)
and sees everything, exactly as today. Setting it happens in `guard` and `org_context`, right
after the caller's membership in that org was checked. We never grant BYPASSRLS to the app role.
"""

import argparse
import asyncio
import os
import re
import uuid
from collections.abc import Sequence
from contextvars import ContextVar

from sqlalchemy import event, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import Session

from app.config import get_settings

GUC = "app.organization_id"
POLICY = "tenant_isolation"

# Tables with their own organization_id column (the audit log's is nullable).
ORG_TABLES: tuple[str, ...] = (
    "projects",
    "organization_members",
    "organization_invitations",
    "subscriptions",
    "sso_connections",
    "sso_domains",
    "sso_login_requests",
    "scim_directories",
    "scim_users",
    "scim_groups",
    "impersonation_sessions",
)
AUDIT_TABLE = "platform_audit_log"
# `organizations` itself is scoped by its primary key.
ORGANIZATIONS_TABLE = "organizations"
# Tables that belong to a project; a row is visible exactly when its project is.
PROJECT_CHILD_TABLES: tuple[str, ...] = (
    "project_members",
    "auth_custom_fields",
    "entities",
    "generations",
    "project_auth_configs",
    "project_auth_secrets",
    "project_authorizations",
    "project_behavior",
    "project_deployments",
    "project_documents",
    "project_keycloak_configs",
    "project_observability",
    "project_payments_configs",
    "project_roles",
    "project_permissions",
    "project_storage_configs",
    "relations",
    "spec_ops",
)
ALL_TABLES: tuple[str, ...] = (
    ORGANIZATIONS_TABLE,
    *ORG_TABLES,
    AUDIT_TABLE,
    *PROJECT_CHILD_TABLES,
)

_ctx = "nullif(current_setting('app.organization_id', true), '')"
_UNSET = f"{_ctx} IS NULL"
_ORG = f"{_ctx}::uuid"


def _using(table: str) -> str:
    if table == ORGANIZATIONS_TABLE:
        return f"{_UNSET} OR id = {_ORG}"
    if table == AUDIT_TABLE:
        # Platform-level events (no org) stay writable and readable inside a scoped request.
        return f"{_UNSET} OR organization_id IS NULL OR organization_id = {_ORG}"
    if table in PROJECT_CHILD_TABLES:
        return f"{_UNSET} OR project_id IN (SELECT id FROM projects)"
    return f"{_UNSET} OR organization_id = {_ORG}"


def install_statements() -> list[str]:
    out: list[str] = []
    for table in ALL_TABLES:
        out.append(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        out.append(f"CREATE POLICY {POLICY} ON {table} USING ({_using(table)})")
    return out


def uninstall_statements() -> list[str]:
    return [f"DROP POLICY IF EXISTS {POLICY} ON {t}" for t in ALL_TABLES]


def enable_statements() -> list[str]:
    out: list[str] = []
    for table in ALL_TABLES:
        out.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        out.append(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    return out


def disable_statements() -> list[str]:
    out: list[str] = []
    for table in ALL_TABLES:
        out.append(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        out.append(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    return out


async def run(conn: AsyncConnection, statements: Sequence[str]) -> None:
    for statement in statements:
        await conn.execute(text(statement))


async def status(conn: AsyncConnection) -> dict[str, dict[str, bool]]:
    """table -> {policy: has our policy, enabled: RLS on, forced: applies to the owner too}."""
    rows = (
        await conn.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       EXISTS (SELECT 1 FROM pg_policies p
                               WHERE p.tablename = c.relname AND p.policyname = :policy)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = current_schema() AND c.relname = ANY(:tables)
                """
            ),
            {"policy": POLICY, "tables": list(ALL_TABLES)},
        )
    ).all()
    return {r[0]: {"enabled": r[1], "forced": r[2], "policy": r[3]} for r in rows}


# -- the application's database role (SEC M-1) ---------------------------------------------
# RLS binds nobody who is a superuser or has BYPASSRLS. The API must connect as a plain role;
# migrations (and `install`/`enable`/`create-app-role`) run as the owner role through
# BUILDER_MIGRATIONS_DATABASE_URL.

_IDENT = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def app_role_statements(role: str, password: str, owner: str, database: str) -> list[str]:
    """Idempotent statements that create/refresh the least-privilege API role. `password` must
    already be a safe literal (see `_quote`); names are validated, never interpolated raw."""
    for name in (role, owner, database):
        if not _IDENT.fullmatch(name):
            raise ValueError(f"unsafe identifier: {name!r}")
    flags = "LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION"
    return [
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') "
        f"THEN CREATE ROLE {role} {flags} PASSWORD {password}; "
        f"ELSE ALTER ROLE {role} {flags} PASSWORD {password}; END IF; END $$",
        f"GRANT CONNECT ON DATABASE {database} TO {role}",
        f"GRANT USAGE ON SCHEMA public TO {role}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {role}",
    ]


def _quote(value: str) -> str:
    # The literal sits inside a DO $$ block run through text(): `$` would end the block and
    # `:name` would be read as a bind parameter. Refuse rather than escape.
    if any(ch in value for ch in "$:\\\x00"):
        raise ValueError("the password must not contain '$', ':', backslash or NUL")
    return "'" + value.replace("'", "''") + "'"


async def role_problems(conn: AsyncConnection) -> list[str]:
    """Why the connected role would defeat RLS (empty = fine)."""
    row = (
        await conn.execute(
            text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
    ).one()
    problems = []
    if row[1]:
        problems.append(f"role {row[0]!r} is a superuser")
    if row[2]:
        problems.append(f"role {row[0]!r} has BYPASSRLS")
    return problems


async def assert_role_enforces_rls(engine: AsyncEngine) -> None:
    """Startup guard: with BUILDER_RLS_ENABLED on, refuse to run as a role RLS cannot bind."""
    async with engine.connect() as conn:
        problems = await role_problems(conn)
    if problems:
        raise RuntimeError(
            "BUILDER_RLS_ENABLED is on but " + "; ".join(problems) + ". Connect the API as the "
            "non-privileged role (python -m app.core.rls create-app-role) and keep the owner "
            "role in BUILDER_MIGRATIONS_DATABASE_URL."
        )


# -- per-request scope ---------------------------------------------------------------------

_current: ContextVar[uuid.UUID | None] = ContextVar("rls_organization_id", default=None)
_BIND = text("SELECT set_config('app.organization_id', :org, true)")


def is_enabled() -> bool:
    return get_settings().rls_enabled


def current() -> uuid.UUID | None:
    return _current.get()


def clear() -> None:
    """End of request. A ContextVar set in a request task dies with it under a real server, but
    an in-process test client reuses the caller's task, so the middleware clears it."""
    _current.set(None)


def _on_begin(session: Session, transaction: object, connection: Connection) -> None:
    org = _current.get()
    if org is not None:
        connection.execute(_BIND, {"org": str(org)})


def install_hook() -> None:
    """Re-bind at the start of every later transaction of the request (a handler commits, the
    next statement opens a new transaction, and SET LOCAL has ended with the old one)."""
    if not event.contains(Session, "after_begin", _on_begin):
        event.listen(Session, "after_begin", _on_begin)


def remove_hook() -> None:
    if event.contains(Session, "after_begin", _on_begin):
        event.remove(Session, "after_begin", _on_begin)


async def bind(db: AsyncSession, organization_id: uuid.UUID) -> None:
    """Confine the rest of this request to one org. A no-op while the flag is off."""
    if not is_enabled():
        return
    install_hook()
    _current.set(organization_id)
    if db.in_transaction():
        await db.execute(_BIND, {"org": str(organization_id)})


async def release(db: AsyncSession) -> None:
    """Lift the confinement for the rest of this request: the few org-scoped actions that
    legitimately touch a second org (moving a project to another org)."""
    if _current.get() is None:
        return
    _current.set(None)
    if db.in_transaction():
        await db.execute(_BIND, {"org": ""})


# -- command line ------------------------------------------------------------------------


async def _main(command: str, yes: bool) -> int:
    if command == "enable" and not yes:
        print(
            "This turns row-level security ON for "
            f"{len(ALL_TABLES)} tables of the database in BUILDER_DATABASE_URL.\n"
            "Read docs/MULTITENANT_ARCHITECTURE.md (rollout) first; repeat with --yes."
        )
        return 1
    settings = get_settings()
    owner_url = settings.migrations_database_url or settings.database_url
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            if command == "check-role":
                api = create_async_engine(settings.database_url)
                try:
                    async with api.connect() as api_conn:
                        problems = await role_problems(api_conn)
                finally:
                    await api.dispose()
                print("API role ok: not superuser, no BYPASSRLS" if not problems else "\n".join(problems))
                return 1 if problems else 0
            if command == "create-app-role":
                password = os.environ.get("BUILDER_APP_DB_PASSWORD", "")
                if len(password) < 12:
                    print("Set BUILDER_APP_DB_PASSWORD (at least 12 characters) first.")
                    return 1
                role = os.environ.get("BUILDER_APP_DB_ROLE", "builder_app")
                owner = make_url(owner_url)
                stmts = app_role_statements(
                    role, _quote(password), owner.username or "builder", owner.database or "builder"
                )
                await run(conn, stmts)
                print(f"role {role}: {len(stmts)} statements applied (no secrets printed)")
                return 0
            if command == "status":
                for table, info in sorted((await status(conn)).items()):
                    print(
                        f"{table:32} policy={info['policy']!s:5} on={info['enabled']!s:5} "
                        f"forced={info['forced']}"
                    )
                return 0
            statements = {
                "install": install_statements(),
                "uninstall": uninstall_statements(),
                "enable": enable_statements(),
                "disable": disable_statements(),
            }[command]
            await run(conn, statements)
            print(f"{command}: {len(statements)} statements applied")
            return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.core.rls", description=__doc__)
    parser.add_argument("command", choices=["status", "install", "uninstall", "enable", "disable", "create-app-role", "check-role"])
    parser.add_argument("--yes", action="store_true", help="confirm `enable`")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.command, args.yes)))


if __name__ == "__main__":
    main()
