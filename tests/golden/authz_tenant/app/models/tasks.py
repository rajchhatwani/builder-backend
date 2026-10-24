"""SQLAlchemy model for Task (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.labels import Label


class Task(_models_base.Base):
    __tablename__ = "tasks"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    title: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    done: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    points: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    created_by_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(
        _sa.ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )
    deleted_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )

    labels: _orm.Mapped[list["Label"]] = _orm.relationship('Label', secondary='tasks_labels', primaryjoin="Task.id == tasks_labels.c.left_id", secondaryjoin="Label.id == tasks_labels.c.right_id", back_populates='tasks', passive_deletes=True)
