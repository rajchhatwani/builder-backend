"""Platform-side data import (B4-1, C16): previewed batches, their rows, and the canonical store.

The builder cannot reach a generated app's database, so committed records land here, per project
and entity. Delivery into a running preview or generated app is a later generator work package.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, _utcnow

BATCH_STATES = ("previewed", "committed", "cancelled")
ROW_STATES = ("accepted", "rejected", "fixed", "duplicate")


def _project_fk() -> ForeignKey:
    return ForeignKey("projects.id", ondelete="CASCADE")


class ImportBatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (Index("ix_import_batches_project", "project_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(120), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="previewed")
    headers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportRow(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        Index("ix_import_rows_batch", "batch_id", "row_no"),
        Index("ix_import_rows_batch_status", "batch_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    record: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    dedupe_key: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ImportedRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "imported_records"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "entity_name", "dedupe_key", name="uq_imported_records_key"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
