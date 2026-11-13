"""ai pack: eval harness table

Revision ID: 0042
Revises: 0041
Create Date: rendered from the spec by Backend Builder

ai_eval_runs holds one finished run of an eval suite (score in basis points, passed, one result per case as JSONB).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_eval_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("suite", sa.String(length=40), nullable=False),
        sa.Column("agent", sa.String(length=40), nullable=False),
        sa.Column("score_bp", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("score_bp >= 0 AND score_bp <= 10000", name="ck_ai_eval_runs_score"),
        sa.CheckConstraint("total >= 0 AND passed_count >= 0 AND passed_count <= total", name="ck_ai_eval_runs_counts"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_ai_eval_runs_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_eval_runs_tenant_id"), "ai_eval_runs", ["tenant_id"], unique=False)
    op.create_index("ix_ai_eval_runs_suite_created_at", "ai_eval_runs", ["suite", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("ai_eval_runs")
