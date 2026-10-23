"""storage tables

Revision ID: 0004
Revises: 0003
Create Date: rendered from the spec by Backend Builder

File metadata and the audit trail. The audit table is protected by triggers: rows cannot be updated,
the table cannot be truncated, and rows cannot be deleted before they are 3650 days old (and then
only by the maintenance command).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stor_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=True),
        sa.Column("declared_type", sa.String(100), nullable=False),
        sa.Column("detected_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_engine", sa.String(100), nullable=True),
        sa.Column("quarantine_reason", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_stor_files"),
        sa.UniqueConstraint("storage_key", name="uq_stor_files_storage_key"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_stor_files_size"),
        sa.CheckConstraint(
            "status IN ('pending', 'clean', 'quarantined', 'deleting', 'deleted')",
            name="ck_stor_files_status",
        ),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_stor_files_sha256"),
    )
    op.create_index("ix_stor_files_tenant_created", "stor_files", ["tenant_id", "created_at"])
    op.create_index("ix_stor_files_creator_created", "stor_files", ["created_by_id", "created_at"])
    op.create_index("ix_stor_files_status_updated", "stor_files", ["status", "updated_at"])

    op.create_table(
        "stor_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_key", sa.String(80), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("outcome", sa.String(12), nullable=False),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_stor_audit_log"),
        sa.UniqueConstraint("chain_key", "seq", name="uq_stor_audit_log_chain_seq"),
    )
    op.create_index("ix_stor_audit_log_actor_at", "stor_audit_log", ["actor_id", "at"])
    op.create_index("ix_stor_audit_log_file_at", "stor_audit_log", ["file_id", "at"])
    op.create_index("ix_stor_audit_log_at", "stor_audit_log", ["at"])

    op.execute(
        """
        CREATE FUNCTION stor_audit_protect() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF current_setting('storage.allow_audit_purge', true) = 'on'
                   AND OLD.at < now() - make_interval(days => 3650) THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'stor_audit_log rows cannot be deleted before the retention period';
            END IF;
            RAISE EXCEPTION 'stor_audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER stor_audit_append_only BEFORE UPDATE OR DELETE ON stor_audit_log "
        "FOR EACH ROW EXECUTE FUNCTION stor_audit_protect()"
    )
    op.execute(
        "CREATE TRIGGER stor_audit_no_truncate BEFORE TRUNCATE ON stor_audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION stor_audit_protect()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS stor_audit_no_truncate ON stor_audit_log")
    op.execute("DROP TRIGGER IF EXISTS stor_audit_append_only ON stor_audit_log")
    op.execute("DROP FUNCTION IF EXISTS stor_audit_protect()")
    op.drop_table("stor_audit_log")
    op.drop_table("stor_files")
