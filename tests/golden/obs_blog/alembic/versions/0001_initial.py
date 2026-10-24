"""initial schema

Revision ID: 0001
Revises:
Create Date: rendered from the spec by Backend Builder

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_comments"),
    )
    op.create_index("ix_comments_post_id", "comments", ["post_id"])
    op.create_table(
        "posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_posts"),
    )
    op.create_index("ix_posts_author_id", "posts", ["author_id"])
    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
        sa.UniqueConstraint("name", name="uq_tags_name"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "posts_tags",
        sa.Column("left_id", sa.Uuid(), nullable=False),
        sa.Column("right_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["left_id"], ["posts.id"], name="fk_posts_tags_left_id_posts", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["right_id"], ["tags.id"], name="fk_posts_tags_right_id_tags", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("left_id", "right_id", name="pk_posts_tags"),
    )
    op.create_foreign_key(
        "fk_comments_post_id_posts",
        "comments",
        "posts",
        ["post_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_posts_author_id_users",
        "posts",
        "users",
        ["author_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_posts_author_id_users", "posts", type_="foreignkey")
    op.drop_constraint("fk_comments_post_id_posts", "comments", type_="foreignkey")
    op.drop_table("posts_tags")
    op.drop_table("users")
    op.drop_table("tags")
    op.drop_table("posts")
    op.drop_table("comments")
