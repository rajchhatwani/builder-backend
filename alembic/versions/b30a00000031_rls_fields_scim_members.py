"""RLS policy for the child tables the first list missed (S2-010)

Revision ID: b30a00000031
Revises: b30a0000002f
Create Date: 2026-11-08

`fields` (via its entity) and `scim_group_members` (via its group) have no organization_id or
project_id, so the original lists skipped them; `ai_spend_reservations` (org id NULL for platform
rows, which stay visible like the audit log's) was added after the list was written. Policy only; turning RLS on stays the separate
`python -m app.core.rls enable --yes` step (re-run it if RLS is already on, to cover these two).
The unset-GUC fail-open behaviour is accepted (see app/core/rls.py).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b30a00000031"
down_revision: str | Sequence[str] | None = "b30a0000002f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNSET = "nullif(current_setting('app.organization_id', true), '') IS NULL"
# table -> (column, parent): frozen here on purpose
_TABLES = {
    "fields": ("entity_id", "entities"),
    "scim_group_members": ("group_id", "scim_groups"),
}
_NULL_ORG_TABLES = ("ai_spend_reservations",)


def upgrade() -> None:
    for table, (column, parent) in _TABLES.items():
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_UNSET} OR {column} IN (SELECT id FROM {parent}))"
        )


    for table in _NULL_ORG_TABLES:
        ctx = "nullif(current_setting('app.organization_id', true), '')"
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_UNSET} OR organization_id IS NULL OR organization_id = {ctx}::uuid)"
        )


def downgrade() -> None:
    for table in (*_TABLES, *_NULL_ORG_TABLES):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
