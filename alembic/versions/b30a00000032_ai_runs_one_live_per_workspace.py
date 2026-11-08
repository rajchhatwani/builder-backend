"""One live agent run per workspace

Revision ID: b30a00000032
Revises: b30a00000031
Create Date: 2026-11-08

S1-006: two live runs on one worktree overwrite each other's files and stale each other's
approvals. A partial unique index makes the second one impossible. Pre-existing duplicates (older
live runs on a workspace that has a newer live run) are stopped first so the index can be built.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b30a00000032"
down_revision: str | Sequence[str] | None = "b30a00000031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE = "('created','planning','awaiting_approval','running','gating','applying')"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE ai_runs SET state = 'stopped', stop_code = 'superseded',
               stop_detail = 'another live run on the same workspace', finished_at = now(),
               lease_owner = NULL, lease_until = NULL
        WHERE workspace_id IS NOT NULL AND state IN {_LIVE}
          AND id NOT IN (
            SELECT DISTINCT ON (workspace_id) id FROM ai_runs
            WHERE workspace_id IS NOT NULL AND state IN {_LIVE}
            ORDER BY workspace_id, created_at DESC, id)
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX uq_ai_runs_live_workspace ON ai_runs (workspace_id) "
        f"WHERE workspace_id IS NOT NULL AND state IN {_LIVE}"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_ai_runs_live_workspace")
