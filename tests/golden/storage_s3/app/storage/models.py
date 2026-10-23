"""File tables (generated). They are created by alembic/versions/0004_storage.py.

Only metadata lives here. The bytes are in the bucket, under a key made of ids and a date, so a
file's name or content never decides where it is stored.
"""

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.models._base import Base, utcnow

# pending: being stored. clean: scanned and available. quarantined: blocked (manual, or a rescan
# found something). deleting / deleted: erasure in progress / done (only a tombstone is kept).
STATUSES = ("pending", "clean", "quarantined", "deleting", "deleted")


class StorFile(Base):
    __tablename__ = "stor_files"
    __table_args__ = (
        sa.CheckConstraint("size_bytes >= 0", name="ck_stor_files_size"),
        sa.CheckConstraint(
            "status IN ('pending', 'clean', 'quarantined', 'deleting', 'deleted')",
            name="ck_stor_files_status",
        ),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_stor_files_sha256"),
        sa.Index("ix_stor_files_tenant_created", "tenant_id", "created_at"),
        sa.Index("ix_stor_files_creator_created", "created_by_id", "created_at"),
        sa.Index("ix_stor_files_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(12), nullable=False)
    shared: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=False)
    # What the uploader called it: shown back, never trusted. Blanked when the file is erased.
    original_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    declared_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    # What the bytes really are (see sniff.py); this decides how the file is served.
    detected_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger(), nullable=False)
    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(sa.String(300), nullable=False, unique=True)
    scanned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    scan_engine: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    quarantine_reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class StorAuditLog(Base):
    """Append-only (database triggers refuse UPDATE, DELETE before the retention period, TRUNCATE)."""

    __tablename__ = "stor_audit_log"
    __table_args__ = (
        sa.UniqueConstraint("chain_key", "seq", name="uq_stor_audit_log_chain_seq"),
        sa.Index("ix_stor_audit_log_actor_at", "actor_id", "at"),
        sa.Index("ix_stor_audit_log_file_at", "file_id", "at"),
        sa.Index("ix_stor_audit_log_at", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    chain_key: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    seq: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    event: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    outcome: Mapped[str] = mapped_column(sa.String(12), nullable=False)
    ip: Mapped[str | None] = mapped_column(sa.String(45), nullable=True)
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB(), nullable=False)
    prev_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
