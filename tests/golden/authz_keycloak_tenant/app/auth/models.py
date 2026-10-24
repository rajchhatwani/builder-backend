"""SQLAlchemy models for authentication with Keycloak (generated).

Passwords, tokens and sign-in live in Keycloak. This project keeps one profile row per user,
keyed by the user's Keycloak id, so the data people create can point at them.
"""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


class AuthTenant(_models_base.Base):
    """A tenant: one Keycloak organization. Created the first time one of its members calls the
    API; its id is derived from the organization's alias, so it is the same in every environment."""

    __tablename__ = "auth_tenants"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )


class AuthUser(_models_base.Base):
    """The profile of a Keycloak user, created the first time they call the API.

    `id` is the user's Keycloak id (the token's `sub`). Name, email, roles and the custom
    attributes are refreshed from the token whenever they change; none of them is a credential."""

    __tablename__ = "auth_users"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    email: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(320), nullable=True, index=True)
    name: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True)
    roles: _orm.Mapped[list[str]] = _orm.mapped_column(_pg.JSONB(), nullable=False, default=list)
    # The organization of the token this user last called with.
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # A local switch: set it to false to refuse this user here without touching Keycloak.
    is_active: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False, default=True)
    deleted_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    age: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    born: _orm.Mapped[_dt.date | None] = _orm.mapped_column(_sa.Date(), nullable=True)
    company: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(80), nullable=True)
    mobile: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True)
    newsletter: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True)
    notes: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    plan: _orm.Mapped[_t.Literal['free', 'pro'] | None] = _orm.mapped_column(_sa.String(64), nullable=True)
    score: _orm.Mapped[float | None] = _orm.mapped_column(_sa.Float(), nullable=True)
    site: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    __table_args__ = (
        _sa.Index("ix_auth_users_site", "site"),
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
