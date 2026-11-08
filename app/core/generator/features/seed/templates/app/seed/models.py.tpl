"""Which rows the seed created (generated): `--reset` deletes exactly these and nothing else."""

import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class SeedRow(_models_base.Base):
    __tablename__ = "seed_rows"

    table_name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), primary_key=True)
    record_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    profile: _orm.Mapped[str] = _orm.mapped_column(_sa.String(24), nullable=False)
    plan_hash: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
