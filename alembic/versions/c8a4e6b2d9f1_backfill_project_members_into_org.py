"""Project members must belong to the project's org (review F-012; plan §3.2)

The first backfill moved every project under its owner's personal org but left the other
`project_members` outside it: they kept project access without an org seat, so org offboarding and
SCIM could not remove them. Each such person is added to the project's org as a `member`
(access is kept, nothing is dropped). Seats are not enforced retroactively: an org that now
holds more people than its plan allows simply cannot invite more until it upgrades.

Idempotent. Not reversible in data (the added rows can't be told apart afterwards); the
downgrade is a no-op, which is safe because the rows are valid under the older schema too.

Revision ID: c8a4e6b2d9f1
Revises: b3d7f1a9c5e2
Create Date: 2026-10-27
"""

from alembic import op

revision = "c8a4e6b2d9f1"
down_revision = "b3d7f1a9c5e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO organization_members (organization_id, user_id, role, joined_at)
        SELECT DISTINCT ON (p.organization_id, pm.user_id)
               p.organization_id, pm.user_id, 'member', now()
        FROM project_members pm
        JOIN projects p ON p.id = pm.project_id
        WHERE p.organization_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM organization_members om
              WHERE om.organization_id = p.organization_id AND om.user_id = pm.user_id
          )
        ORDER BY p.organization_id, pm.user_id
        """
    )


def downgrade() -> None:
    pass
