"""The token vault table (generated). Holds the encrypted original of every token; never a plain value."""

import datetime as _dt

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class RegulatedToken(_models_base.Base):
    __tablename__ = "regulated_tokens"

    token: _orm.Mapped[str] = _orm.mapped_column(_sa.Text(), primary_key=True)
    ciphertext: _orm.Mapped[str] = _orm.mapped_column(_sa.Text(), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
