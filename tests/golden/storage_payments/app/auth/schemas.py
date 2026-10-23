"""Request and response models for the auth endpoints (generated)."""
import datetime as _dt
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


class PasswordResetRequest(_Request):
    """Name the account by `email` or by `phone` (not both)."""

    email: str | None = _pd.Field(default=None, max_length=320, pattern=_EMAIL_PATTERN)
    phone: str | None = _pd.Field(default=None, pattern=_PHONE_PATTERN)

    lower_email = _pd.field_validator("email", mode="before")(_normalise_email)

    @_pd.model_validator(mode="after")
    def exactly_one(self) -> "PasswordResetRequest":
        if (self.email is None) == (self.phone is None):
            raise ValueError("provide exactly one of email or phone")
        return self


class PasswordResetConfirm(_Request):
    """Confirm with the emailed `token`, or with the SMS `code` plus the `phone` it went to."""

    new_password: str = _pd.Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)
    token: str | None = _pd.Field(default=None, min_length=1, max_length=256)
    phone: str | None = _pd.Field(default=None, pattern=_PHONE_PATTERN)
    code: str | None = _pd.Field(default=None, pattern=r"^[0-9]{6}$")

    @_pd.model_validator(mode="after")
    def token_or_code(self) -> "PasswordResetConfirm":
        by_token = self.token is not None and self.phone is None and self.code is None
        by_code = self.token is None and self.phone is not None and self.code is not None
        if not (by_token or by_code):
            raise ValueError("provide either token, or phone together with code")
        return self


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


class Accepted(_pd.BaseModel):
    """Answer to requests that must not reveal whether an account exists."""

    detail: str = "if the account exists, a message has been sent"
