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


class AuthTenant(_models_base.Base):
    """A tenant: one Keycloak organization. Created the first time one of its members calls the
    API; its id is derived from the organization's alias, so it is the same in every environment."""

    __tablename__ = "auth_tenants"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False)
    # Namespaced reference used by a suite hub ("<suite_id>:<alias>"). The local id stays the key.
    external_ref: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True, unique=True)
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

    `id` is the app's own user id, NOT the token's `sub`. The `sub` (with its issuer) is kept in
    `auth_identities` and maps to this id; a `sub` that happens to be a UUID is reused as the id
    when that id is free, any other `sub` gets a stable id derived from issuer and `sub`. Name, email,
    roles and the custom attributes are refreshed from the token whenever they change; none of them
    is a credential."""

    __tablename__ = "auth_users"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    email: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(320), nullable=True, index=True)
    name: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True)
    roles: _orm.Mapped[list[str]] = _orm.mapped_column(_pg.JSONB(), nullable=False, default=list)
    # "local": roles are set in this app. "idp": a hub or identity provider is the master.
    role_source: _orm.Mapped[str] = _orm.mapped_column(
        _sa.String(10), nullable=False, default="idp", server_default="idp"
    )
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


class AuthIdentity(_models_base.Base):
    """Links one local user to one identity at an issuer. The local `auth_users.id` never changes;
    the token's `(issuer, subject)` pair is only a way to find it."""

    __tablename__ = "auth_identities"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    user_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issuer: _orm.Mapped[str] = _orm.mapped_column(_sa.String(512), nullable=False)
    subject: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False)
    provider: _orm.Mapped[str] = _orm.mapped_column(_sa.String(20), nullable=False)
    email_at_link: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(320), nullable=True)
    email_verified: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False, default=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    last_seen_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (_sa.UniqueConstraint("issuer", "subject", name="uq_auth_identities_issuer_subject"),)


class AuthSession(_models_base.Base):
    """One sign-in. `sid` is the session id the identity provider put in the token (built-in:
    the refresh-token family). Revoking it ends the session without touching the user."""

    __tablename__ = "auth_sessions"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    user_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sid: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False)
    issuer: _orm.Mapped[str] = _orm.mapped_column(_sa.String(512), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    last_seen_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    revoked_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (_sa.UniqueConstraint("issuer", "sid", name="uq_auth_sessions_issuer_sid"),)


class AuthProviderLock(_models_base.Base):
    """One row: which identity provider this database was started with."""

    __tablename__ = "auth_provider_lock"

    id: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), primary_key=True, autoincrement=False)
    provider: _orm.Mapped[str] = _orm.mapped_column(_sa.String(20), nullable=False)
    realm: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(63), nullable=True)
    issuer: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(512), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )
