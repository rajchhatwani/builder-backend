"""regulated mode: the token vault

Revision ID: 0043
Revises: 0017
Create Date: rendered from the spec by Backend Builder

`regulated_tokens` holds the encrypted original of every token (AES-256-GCM, AAD `regulated_tokens.value`). The
encrypted columns themselves, and the `<field>_bidx` blind-index columns, are created by the initial migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "regulated_tokens",
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("token", name="pk_regulated_tokens"),
    )


def downgrade() -> None:
    op.drop_table("regulated_tokens")
