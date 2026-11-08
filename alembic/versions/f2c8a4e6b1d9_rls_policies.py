"""Row-level security policies (§3.3) - installed, NOT enabled

Creates the `tenant_isolation` policy on every org-scoped table. A policy does nothing until a
table has RLS enabled, and this migration never enables it: that is a separate, deliberate
step (`python -m app.core.rls enable --yes`, see docs/MULTITENANT_ARCHITECTURE.md). The table
lists are frozen here on purpose; later tables get their own migration.

Revision ID: f2c8a4e6b1d9
Revises: e7d3b9a1c5f2
Create Date: 2026-10-28
"""

from alembic import op

revision = "f2c8a4e6b1d9"
down_revision = "e7d3b9a1c5f2"
branch_labels = None
depends_on = None

ORG_TABLES = (
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
CHILD_TABLES = (
    "project_members",
    "auth_custom_fields",
    "entities",
    "generations",
    "project_auth_configs",
    "project_auth_secrets",
    "project_authorizations",
    "project_deployments",
    "project_documents",
    "project_keycloak_configs",
    "project_observability",
    "project_payments_configs",
    "project_roles",
    "project_permissions",
    "project_storage_configs",
    "relations",
)
ALL_TABLES = ("organizations", *ORG_TABLES, "platform_audit_log", *CHILD_TABLES)

_CTX = "nullif(current_setting('app.organization_id', true), '')"


def _using(table: str) -> str:
    unset = f"{_CTX} IS NULL"
    if table == "organizations":
        return f"{unset} OR id = {_CTX}::uuid"
    if table == "platform_audit_log":
        return f"{unset} OR organization_id IS NULL OR organization_id = {_CTX}::uuid"
    if table in CHILD_TABLES:
        return f"{unset} OR project_id IN (SELECT id FROM projects)"
    return f"{unset} OR organization_id = {_CTX}::uuid"


def upgrade() -> None:
    for table in ALL_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_using(table)})")


def downgrade() -> None:
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
