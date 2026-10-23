"""SQLAlchemy models for authentication with Keycloak (generated).

Passwords, tokens and sign-in live in Keycloak. This project keeps one profile row per user,
keyed by the user's Keycloak id, so the data people create can point at them.
"""
import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


class AuthUser(_models_base.Base):
    """The profile of a Keycloak user, created the first time they call the API.

    `id` is the user's Keycloak id (the token's `sub`). Name, email and roles are refreshed
    from the token whenever they change; none of them is a credential."""

    __tablename__ = "auth_users"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    email: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(320), nullable=True, index=True)
    name: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True)
    roles: _orm.Mapped[list[str]] = _orm.mapped_column(_pg.JSONB(), nullable=False, default=list)
    # A local switch: set it to false to refuse this user here without touching Keycloak.
    is_active: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False, default=True)
    deleted_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
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


class AuthProviderLock(_models_base.Base):
    """One row: which identity provider this database was started with."""

    __tablename__ = "auth_provider_lock"

    id: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), primary_key=True, autoincrement=False)
    provider: _orm.Mapped[str] = _orm.mapped_column(_sa.String(20), nullable=False)
    realm: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(63), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )
