"""Pydantic schemas for project auth secrets (builder API layer).

Security contract:
  - AuthSecretsWrite  : accepts plaintext values from the dashboard.
                        All fields optional — partial updates are safe.
  - AuthSecretsStatus : the ONLY response shape — returns booleans,
                        never plaintext or ciphertext.

We deliberately have NO read schema that returns actual values.
The `PUT /projects/{id}/auth/secrets` endpoint returns AuthSecretsStatus
immediately after writing so the dashboard can show "✓ configured" badges.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import SmsProvider


class SmtpSecretsWrite(BaseModel):
    """SMTP credential fragment.

    `username` is optional — many providers (SendGrid, Mailgun) use a fixed
    username ("apikey", "api") and only need the API key as password.
    """

    username: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=1, max_length=500)


class TwilioSecretsWrite(BaseModel):
    account_sid: str = Field(min_length=1, max_length=100)
    auth_token: str = Field(min_length=1, max_length=100)


class VonageSecretsWrite(BaseModel):
    api_key: str = Field(min_length=1, max_length=100)
    api_secret: str = Field(min_length=1, max_length=100)


class AwsSnsSecretsWrite(BaseModel):
    access_key_id: str = Field(min_length=1, max_length=128)
    secret_access_key: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=30)


class AuthSecretsWrite(BaseModel):
    """Request body for PUT /projects/{id}/auth/secrets.

    Send only the credential groups that changed.  Omitting a group leaves
    any previously stored secrets for that group intact (partial update).
    Sending a group with null/missing fields clears that group.

    Cross-validation: if sms_provider is specified, the matching secret
    block must be present.
    """

    smtp: SmtpSecretsWrite | None = None

    # Supply at most one SMS provider block; which provider is active is
    # controlled by ProjectAuthConfig.sms_provider.
    twilio: TwilioSecretsWrite | None = None
    vonage: VonageSecretsWrite | None = None
    aws_sns: AwsSnsSecretsWrite | None = None

    # Optional: if supplied, validated against the configured sms_provider.
    # The service re-validates against the DB config if not provided here.
    sms_provider: SmsProvider | None = None

    @model_validator(mode="after")
    def check_sms_provider_match(self) -> "AuthSecretsWrite":
        """If sms_provider is given in this request, the matching block must be present."""
        provider = self.sms_provider
        if provider is None:
            return self
        if provider == SmsProvider.twilio and self.twilio is None:
            raise ValueError("twilio credentials are required when sms_provider is 'twilio'")
        if provider == SmsProvider.vonage and self.vonage is None:
            raise ValueError("vonage credentials are required when sms_provider is 'vonage'")
        if provider == SmsProvider.aws_sns and self.aws_sns is None:
            raise ValueError("aws_sns credentials are required when sms_provider is 'aws_sns'")
        return self


# ── Status (the only response shape — never returns plaintext) ────────────────


class SmtpSecretsStatus(BaseModel):
    configured: bool
    username_set: bool  # whether a custom username was supplied


class SmsSecretsStatus(BaseModel):
    provider: SmsProvider | None
    configured: bool


class AuthSecretsStatus(BaseModel):
    """Response body for GET /projects/{id}/auth/secrets/status and PUT.

    Returns booleans only — never plaintext or ciphertext credentials.
    """

    model_config = {"from_attributes": True}

    project_id: uuid.UUID
    smtp: SmtpSecretsStatus
    sms: SmsSecretsStatus
    updated_at: datetime
