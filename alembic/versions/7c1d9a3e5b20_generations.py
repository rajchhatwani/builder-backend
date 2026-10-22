"""generations

Revision ID: 7c1d9a3e5b20
Revises: 4ba005f84fc9
Create Date: 2026-10-22 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7c1d9a3e5b20'
down_revision: str | Sequence[str] | None = '4ba005f84fc9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('generations',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('spec_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('spec_hash', sa.String(length=64), nullable=False),
    sa.Column('file_manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_generations_project_id_created_at', 'generations', ['project_id', 'created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_generations_project_id_created_at', table_name='generations')
    op.drop_table('generations')
