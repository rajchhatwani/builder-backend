"""Project slugs are unique per organization, not across all tenants (FEAT F-2)

Revision ID: a3d9c1e7b5f4
Revises: f2c8a4e6b1d9
Create Date: 2026-10-31
"""

from alembic import op

revision = "a3d9c1e7b5f4"
down_revision = "f2c8a4e6b1d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("projects_slug_key", "projects", type_="unique")
    op.create_unique_constraint("uq_projects_org_slug", "projects", ["organization_id", "slug"])


def downgrade() -> None:
    # Re-creating the global constraint would fail on slugs now shared between orgs:
    # keep the oldest project's slug and suffix the others with a short id fragment.
    op.execute(
        """
        UPDATE projects p SET slug = left(p.slug, 90) || '-' || left(p.id::text, 8)
        WHERE EXISTS (
            SELECT 1 FROM projects q
            WHERE q.slug = p.slug AND (q.created_at, q.id) < (p.created_at, p.id)
        )
        """
    )
    op.drop_constraint("uq_projects_org_slug", "projects", type_="unique")
    op.create_unique_constraint("projects_slug_key", "projects", ["slug"])
