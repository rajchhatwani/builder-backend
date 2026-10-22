"""initial schema

Revision ID: 0001
Revises:
Create Date: rendered from the spec by Backend Builder

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("born_on", sa.Date(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_authors"),
        sa.UniqueConstraint("name", name="uq_authors_name"),
    )
    op.create_table(
        "books",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("isbn", sa.String(20), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(18, 6), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.Column("catalog_id", sa.Uuid(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("shelf_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_books"),
        sa.UniqueConstraint("isbn", name="uq_books_isbn"),
    )
    op.create_index("ix_books_author_id", "books", ["author_id"])
    op.create_index("ix_books_shelf_id", "books", ["shelf_id"])
    op.create_index("ix_books_title", "books", ["title"])
    op.create_table(
        "members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("email", sa.String(120), nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=True),
        sa.Column("sponsor_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_members"),
        sa.UniqueConstraint("email", name="uq_members_email"),
    )
    op.create_index("ix_members_sponsor_id", "members", ["sponsor_id"])
    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_profiles"),
        sa.UniqueConstraint("member_id", name="uq_profiles_member_id"),
    )
    op.create_table(
        "shelves",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_shelves"),
        sa.UniqueConstraint("label", name="uq_shelves_label"),
    )
    op.create_table(
        "books_borrowers",
        sa.Column("left_id", sa.Uuid(), nullable=False),
        sa.Column("right_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["left_id"], ["books.id"], name="fk_books_borrowers_left_id_books", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["right_id"], ["members.id"], name="fk_books_borrowers_right_id_members", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("left_id", "right_id", name="pk_books_borrowers"),
    )
    op.create_foreign_key(
        "fk_books_author_id_authors",
        "books",
        "authors",
        ["author_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_books_shelf_id_shelves",
        "books",
        "shelves",
        ["shelf_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_members_sponsor_id_members",
        "members",
        "members",
        ["sponsor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_profiles_member_id_members",
        "profiles",
        "members",
        ["member_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_profiles_member_id_members", "profiles", type_="foreignkey")
    op.drop_constraint("fk_members_sponsor_id_members", "members", type_="foreignkey")
    op.drop_constraint("fk_books_author_id_authors", "books", type_="foreignkey")
    op.drop_constraint("fk_books_shelf_id_shelves", "books", type_="foreignkey")
    op.drop_table("books_borrowers")
    op.drop_table("shelves")
    op.drop_table("profiles")
    op.drop_table("members")
    op.drop_table("books")
    op.drop_table("authors")
