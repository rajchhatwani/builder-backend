"""projects.organization_id NOT NULL; audit (action, target_id) index

Revision ID: c7e1f3a9d2b4
Revises: b2c3d4e5f6a7
Create Date: 2026-10-26

PLATFORM_SAAS_PLAN §3.2: every project belongs to an organization. Phase A added the column
as nullable and backfilled it; this finishes the job, idempotently:

  1. a project with an owner but no org → the owner's default org (or personal org);
  2. a project with no owner at all (pre-accounts data) → the holding org
     'unclaimed-projects' (no members, created only if needed). The bootstrap administrator
     adopts those projects into their own org at first start;
  3. ALTER COLUMN ... SET NOT NULL.

Also indexes platform_audit_log (action, target_id) for Stripe webhook dedupe at volume.
Downgrade makes the column nullable again and dissolves the holding org.
"""

import sqlalchemy as sa

from alembic import op

revision = "c7e1f3a9d2b4"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

HOLDING_SLUG = "unclaimed-projects"


def upgrade() -> None:
    # 1. Owned projects without an org → an owner's landing org.
    op.execute(
        """
        UPDATE projects p
        SET organization_id = sub.org_id
        FROM (
            SELECT DISTINCT ON (pm.project_id)
                   pm.project_id, COALESCE(u.default_organization_id, personal.id) AS org_id
            FROM project_members pm
            JOIN platform_users u ON u.id = pm.user_id
            LEFT JOIN LATERAL (
                SELECT o.id FROM organizations o
                JOIN organization_members om ON om.organization_id = o.id
                WHERE om.user_id = u.id AND o.kind = 'personal'
                LIMIT 1
            ) personal ON true
            WHERE pm.role = 'owner'
            ORDER BY pm.project_id, pm.created_at
        ) sub
        WHERE p.id = sub.project_id AND p.organization_id IS NULL AND sub.org_id IS NOT NULL
        """
    )
    # 2. Whatever is left has nobody to own it: park it in the holding org.
    op.execute(
        f"""
        INSERT INTO organizations (id, name, slug, kind, created_at, updated_at)
        SELECT gen_random_uuid(), 'Unclaimed projects', '{HOLDING_SLUG}', 'team', now(), now()
        WHERE EXISTS (SELECT 1 FROM projects WHERE organization_id IS NULL)
          AND NOT EXISTS (SELECT 1 FROM organizations WHERE slug = '{HOLDING_SLUG}')
        """
    )
    op.execute(
        f"""
        INSERT INTO subscriptions (organization_id, plan_id, status, updated_at)
        SELECT o.id, 'enterprise', 'active', now() FROM organizations o
        WHERE o.slug = '{HOLDING_SLUG}'
          AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.organization_id = o.id)
        """
    )
    op.execute(
        f"""
        UPDATE projects SET organization_id = (
            SELECT id FROM organizations WHERE slug = '{HOLDING_SLUG}'
        )
        WHERE organization_id IS NULL
        """
    )
    # 3. The invariant, enforced by the database from now on.
    op.alter_column("projects", "organization_id", existing_type=sa.UUID(), nullable=False)
    op.create_index(
        "ix_platform_audit_action_target", "platform_audit_log", ["action", "target_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_platform_audit_action_target", table_name="platform_audit_log")
    op.alter_column("projects", "organization_id", existing_type=sa.UUID(), nullable=True)
    op.execute(
        f"""
        UPDATE projects SET organization_id = NULL WHERE organization_id IN (
            SELECT id FROM organizations WHERE slug = '{HOLDING_SLUG}'
        )
        """
    )
    op.execute(
        f"""
        DELETE FROM subscriptions WHERE organization_id IN (
            SELECT id FROM organizations WHERE slug = '{HOLDING_SLUG}'
        )
        """
    )
    op.execute(f"DELETE FROM organizations WHERE slug = '{HOLDING_SLUG}'")
