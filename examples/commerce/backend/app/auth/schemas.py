"""Request and response models for the auth endpoints (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd

_EMAIL_PATTERN = r"^[^@\s\"'<>]+@[^@\s\"'<>]+\.[^@\s\"'<>]+$"
_PHONE_PATTERN = r"^\+[1-9][0-9]{6,14}$"
_PASSWORD_MIN = 8
_PASSWORD_MAX = 128  # bounds the work a single request can ask of the password hash


def _normalise_email(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


class _Request(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")


class RegisterRequest(_Request):
    email: str = _pd.Field(max_length=320, pattern=_EMAIL_PATTERN)
    password: str = _pd.Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)
    phone: str | None = _pd.Field(default=None, pattern=_PHONE_PATTERN, description="E.164, e.g. +14155550123")
    display_name: str = _pd.Field(max_length=80)
    job_title: str | None = _pd.Field(max_length=80, default=None)
    locale: _t.Literal['en', 'fr', 'de', 'hi', 'ja'] = _pd.Field(default='en')
    marketing_opt_in: bool = _pd.Field(default=False)
    invite_token: str | None = _pd.Field(default=None, min_length=1, max_length=256)
    tenant_name: str | None = _pd.Field(
        default=None,
        min_length=2,
        max_length=80,
        description="Creates a new tenant with you as its admin; omit it when you have an invite_token",
    )

    lower_email = _pd.field_validator("email", mode="before")(_normalise_email)


class LoginRequest(_Request):
    email: str = _pd.Field(max_length=320)
    password: str = _pd.Field(min_length=1, max_length=_PASSWORD_MAX)

    lower_email = _pd.field_validator("email", mode="before")(_normalise_email)


class RefreshRequest(_Request):
    refresh_token: str = _pd.Field(min_length=1, max_length=256)


class TokenRequest(_Request):
    token: str = _pd.Field(min_length=1, max_length=256)


class EmailRequest(_Request):
    email: str = _pd.Field(max_length=320, pattern=_EMAIL_PATTERN)

    lower_email = _pd.field_validator("email", mode="before")(_normalise_email)


class ChangePasswordRequest(_Request):
    current_password: str = _pd.Field(min_length=1, max_length=_PASSWORD_MAX)
    new_password: str = _pd.Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)


class TokenPair(_pd.BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = _pd.Field(description="Access token lifetime in seconds")


class UserRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    email: str
    phone: str | None
    roles: list[str]
    is_active: bool
    email_verified_at: _dt.datetime | None
    phone_verified_at: _dt.datetime | None
    created_at: _dt.datetime
    tenant_id: _uuid.UUID
    display_name: str | None = None
    job_title: str | None = None
    locale: _t.Literal['en', 'fr', 'de', 'hi', 'ja'] | None = None
    marketing_opt_in: bool | None = None


class InvitationCreate(_Request):
    email: str = _pd.Field(max_length=320, pattern=_EMAIL_PATTERN)
    roles: list[_t.Literal['admin', 'catalog', 'customer', 'fulfillment', 'manager', 'marketing', 'support']] = _pd.Field(default_factory=list, max_length=10)

    lower_email = _pd.field_validator("email", mode="before")(_normalise_email)


class InvitationRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    email: str
    roles: list[str]
    expires_at: _dt.datetime
    accepted_at: _dt.datetime | None
    created_at: _dt.datetime


class TenantRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    created_at: _dt.datetime


class Accepted(_pd.BaseModel):
    """Answer to requests that must not reveal whether an account exists."""

    detail: str = "if the account exists, a message has been sent"
