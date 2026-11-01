"""SQLAlchemy models for authentication (generated)."""
import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


class AuthTenant(_models_base.Base):
    """A group of users whose data is kept apart from every other tenant's."""

    __tablename__ = "auth_tenants"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    # Namespaced reference used by a suite hub ("<suite_id>:<alias>"); never part of RLS or `tid`.
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
    __tablename__ = "auth_users"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    email: _orm.Mapped[str] = _orm.mapped_column(_sa.String(320), nullable=False, unique=True)
    phone: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(20), nullable=True, unique=True)
    password_hash: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False)
    roles: _orm.Mapped[list[str]] = _orm.mapped_column(_pg.JSONB(), nullable=False, default=list)
    # "local": roles are set in this app. "idp": a hub or identity provider is the master.
    role_source: _orm.Mapped[str] = _orm.mapped_column(
        _sa.String(10), nullable=False, default="local", server_default="local"
    )
    is_active: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False, default=True)
    email_verified_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    phone_verified_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    last_login_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    deleted_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    handle: _orm.Mapped[str] = _orm.mapped_column(_sa.String(20), nullable=False)
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
        _sa.UniqueConstraint("handle", name="uq_auth_users_handle"),
    )


class AuthRefreshToken(_models_base.Base):
    """One row per issued refresh token; rotation keeps a chain linked by `family_id`."""

    __tablename__ = "auth_refresh_tokens"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    user_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False, index=True)
    token_hash: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, unique=True)
    expires_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False
    )
    revoked_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )


class AuthVerificationCode(_models_base.Base):
    """Email links and SMS codes. Only a hash of the secret is stored."""

    __tablename__ = "auth_verification_codes"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    user_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: _orm.Mapped[str] = _orm.mapped_column(_sa.String(20), nullable=False)
    channel: _orm.Mapped[str] = _orm.mapped_column(_sa.String(5), nullable=False)
    code_hash: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, index=True)
    attempts: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=0)
    expires_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False
    )
    consumed_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )


class AuthInvitation(_models_base.Base):
    """An invitation to register. Only a hash of the emailed token is stored."""

    __tablename__ = "auth_invitations"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    email: _orm.Mapped[str] = _orm.mapped_column(_sa.String(320), nullable=False, index=True)
    roles: _orm.Mapped[list[str]] = _orm.mapped_column(_pg.JSONB(), nullable=False, default=list)
    token_hash: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, unique=True)
    invited_by_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(
        _sa.ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False
    )
    accepted_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
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
