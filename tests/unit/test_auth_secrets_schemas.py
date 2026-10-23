"""Unit tests for auth secrets schemas (Pydantic validation layer).

Pure-Python tests — no DB, no HTTP.
"""

import pytest
from pydantic import ValidationError

from app.models.enums import SmsProvider
from app.schemas.auth_secrets import (
    AuthSecretsWrite,
    AwsSnsSecretsWrite,
    SmtpSecretsWrite,
    TwilioSecretsWrite,
    VonageSecretsWrite,
)

# ── SmtpSecretsWrite ──────────────────────────────────────────────────────────


def test_smtp_password_required() -> None:
    with pytest.raises(ValidationError, match="password"):
        SmtpSecretsWrite(username="user")  # type: ignore[call-arg]


def test_smtp_username_optional() -> None:
    s = SmtpSecretsWrite(password="pass123")
    assert s.username is None
    assert s.password == "pass123"


def test_smtp_empty_password_rejected() -> None:
    with pytest.raises(ValidationError):
        SmtpSecretsWrite(password="")


# ── TwilioSecretsWrite ────────────────────────────────────────────────────────


def test_twilio_requires_both_fields() -> None:
    with pytest.raises(ValidationError):
        TwilioSecretsWrite(account_sid="AC123")  # type: ignore[call-arg]


def test_twilio_valid() -> None:
    t = TwilioSecretsWrite(account_sid="ACxxx", auth_token="token123")
    assert t.account_sid == "ACxxx"


# ── AuthSecretsWrite cross-validation ─────────────────────────────────────────


def test_sms_provider_twilio_requires_twilio_block() -> None:
    with pytest.raises(ValidationError, match="twilio credentials"):
        AuthSecretsWrite(
            sms_provider=SmsProvider.twilio,
            # no twilio block
        )


def test_sms_provider_vonage_requires_vonage_block() -> None:
    with pytest.raises(ValidationError, match="vonage credentials"):
        AuthSecretsWrite(
            sms_provider=SmsProvider.vonage,
        )


def test_sms_provider_aws_requires_aws_block() -> None:
    with pytest.raises(ValidationError, match="aws_sns credentials"):
        AuthSecretsWrite(
            sms_provider=SmsProvider.aws_sns,
        )


def test_twilio_write_without_explicit_provider_is_valid() -> None:
    """Providing credentials without stating provider is allowed (provider
    is read from ProjectAuthConfig in the service layer)."""
    body = AuthSecretsWrite(
        twilio=TwilioSecretsWrite(account_sid="ACxxx", auth_token="tok"),
    )
    assert body.twilio is not None


def test_smtp_only_write_is_valid() -> None:
    body = AuthSecretsWrite(
        smtp=SmtpSecretsWrite(password="smtp-pass"),
    )
    assert body.smtp is not None
    assert body.twilio is None


def test_full_write_with_all_providers() -> None:
    body = AuthSecretsWrite(
        smtp=SmtpSecretsWrite(username="apikey", password="SG.xxx"),
        twilio=TwilioSecretsWrite(account_sid="ACxxx", auth_token="token"),
        vonage=VonageSecretsWrite(api_key="vkey", api_secret="vsecret"),
        aws_sns=AwsSnsSecretsWrite(
            access_key_id="AKIA...",
            secret_access_key="secret",
            region="us-east-1",
        ),
        sms_provider=SmsProvider.twilio,
    )
    assert body.smtp is not None
    assert body.twilio is not None
    assert body.vonage is not None
    assert body.aws_sns is not None


# ── AuthSecretsStatus — no plaintext fields ───────────────────────────────────


def test_auth_secrets_status_has_no_plaintext_fields() -> None:
    """Ensure AuthSecretsStatus has no field that could hold a raw secret value."""
    from app.schemas.auth_secrets import AuthSecretsStatus, SmsSecretsStatus, SmtpSecretsStatus

    # These substrings indicate raw credential storage if present as a field name
    # (excludes _set / _configured boolean suffixes by checking the full name)
    def _looks_like_secret(name: str) -> bool:
        raw_indicators = {"password", "token", "auth_token", "secret_key", "api_secret",
                          "account_sid", "api_key", "access_key"}
        return name in raw_indicators

    all_fields: set[str] = set()
    for model in (AuthSecretsStatus, SmtpSecretsStatus, SmsSecretsStatus):
        all_fields |= set(model.model_fields.keys())

    leaking = {f for f in all_fields if _looks_like_secret(f)}
    assert leaking == set(), (
        f"AuthSecretsStatus exposes potentially sensitive fields: {leaking}"
    )

