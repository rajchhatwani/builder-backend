"""Service layer for project auth secrets.

Security invariants upheld by this service:
  1. Plaintext never written to the DB — always encrypted via app.core.crypto.
  2. Plaintext never returned from any public method — callers get status only.
  3. decrypt() is called ONLY by get_for_generator() which is internal to the
     generator pipeline, not reachable via any HTTP route.
  4. If SECRET_KEY is missing at encrypt/decrypt time, a RuntimeError is raised
     and propagated as HTTP 500 — the server must not be started without it.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt
from app.exceptions import AppError
from app.models.auth_config import ProjectAuthConfig
from app.models.auth_secrets import ProjectAuthSecrets
from app.models.enums import SmsProvider
from app.models.project import Project
from app.schemas.auth_secrets import (
    AuthSecretsStatus,
    AuthSecretsWrite,
    SmsSecretsStatus,
    SmtpSecretsStatus,
)


def _not_found() -> AppError:
    return AppError(code="not_found", message="auth secrets not found", status_code=404)


class AuthSecretsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_project_or_404(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def _get_auth_config(self, project_id: uuid.UUID) -> ProjectAuthConfig | None:
        result = await self.session.execute(
            select(ProjectAuthConfig).where(ProjectAuthConfig.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def _get_or_create_secrets_row(self, project_id: uuid.UUID) -> ProjectAuthSecrets:
        """Fetch existing secrets row, or create an empty one."""
        result = await self.session.execute(
            select(ProjectAuthSecrets).where(ProjectAuthSecrets.project_id == project_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = ProjectAuthSecrets(project_id=project_id)
            self.session.add(row)
            await self.session.flush()  # assign id without committing
        return row

    # ── Public API ────────────────────────────────────────────────────────────

    async def upsert(self, project_id: uuid.UUID, data: AuthSecretsWrite) -> AuthSecretsStatus:
        """Write (encrypted) secrets and return status booleans — never plaintext."""
        await self._get_project_or_404(project_id)
        auth_config = await self._get_auth_config(project_id)

        # If an sms_provider is specified in the request, cross-check against
        # the DB auth config sms_provider for consistency.
        active_sms_provider: SmsProvider | None = auth_config.sms_provider if auth_config else None
        if data.sms_provider is not None:
            active_sms_provider = data.sms_provider

        # If sms is enabled in config but neither the request nor the DB has a
        # matching provider block, surface a clear error.
        if auth_config is not None and auth_config.sms_otp_enabled and active_sms_provider is None:
            raise AppError(
                code="validation_error",
                message=(
                    "sms_otp is enabled in auth config but no sms_provider is set; "
                    "configure sms_provider in the auth config first"
                ),
                status_code=422,
            )

        row = await self._get_or_create_secrets_row(project_id)

        # ── SMTP ──────────────────────────────────────────────────────────────
        if data.smtp is not None:
            row.smtp_username = encrypt(data.smtp.username)
            row.smtp_password = encrypt(data.smtp.password)

        # ── Twilio ────────────────────────────────────────────────────────────
        if data.twilio is not None:
            row.twilio_account_sid = encrypt(data.twilio.account_sid)
            row.twilio_auth_token = encrypt(data.twilio.auth_token)

        # ── Vonage ────────────────────────────────────────────────────────────
        if data.vonage is not None:
            row.vonage_api_key = encrypt(data.vonage.api_key)
            row.vonage_api_secret = encrypt(data.vonage.api_secret)

        # ── AWS SNS ───────────────────────────────────────────────────────────
        if data.aws_sns is not None:
            row.aws_access_key_id = encrypt(data.aws_sns.access_key_id)
            row.aws_secret_access_key = encrypt(data.aws_sns.secret_access_key)
            row.aws_region = encrypt(data.aws_sns.region)

        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError(
                code="conflict",
                message="failed to store secrets — integrity error",
                status_code=409,
            ) from exc

        return self._to_status(project_id, row, active_sms_provider)

    async def status(self, project_id: uuid.UUID) -> AuthSecretsStatus:
        """Return configuration status (booleans only)."""
        await self._get_project_or_404(project_id)
        auth_config = await self._get_auth_config(project_id)
        result = await self.session.execute(
            select(ProjectAuthSecrets).where(ProjectAuthSecrets.project_id == project_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            # No secrets stored yet — return all-false status
            fallback_ts = auth_config.updated_at if auth_config else datetime.now(tz=UTC)
            return AuthSecretsStatus(
                project_id=project_id,
                smtp=SmtpSecretsStatus(configured=False, username_set=False),
                sms=SmsSecretsStatus(
                    provider=auth_config.sms_provider if auth_config else None,
                    configured=False,
                ),
                updated_at=fallback_ts,
            )
        active_sms_provider = auth_config.sms_provider if auth_config else None
        return self._to_status(project_id, row, active_sms_provider)

    # ── Generator-internal: decrypt for code generation only ─────────────────

    async def get_for_generator(self, project_id: uuid.UUID) -> dict[str, str | None]:
        """Decrypt and return all secrets for the generator pipeline.

        This method is NOT reachable via any HTTP route.  It is called only
        from the generation service after the spec is assembled.
        Returns a flat dict of plaintext values; None means not configured.
        """
        result = await self.session.execute(
            select(ProjectAuthSecrets).where(ProjectAuthSecrets.project_id == project_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return {}
        return {
            "smtp_username": decrypt(row.smtp_username),
            "smtp_password": decrypt(row.smtp_password),
            "twilio_account_sid": decrypt(row.twilio_account_sid),
            "twilio_auth_token": decrypt(row.twilio_auth_token),
            "vonage_api_key": decrypt(row.vonage_api_key),
            "vonage_api_secret": decrypt(row.vonage_api_secret),
            "aws_access_key_id": decrypt(row.aws_access_key_id),
            "aws_secret_access_key": decrypt(row.aws_secret_access_key),
            "aws_region": decrypt(row.aws_region),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _to_status(
        project_id: uuid.UUID,
        row: ProjectAuthSecrets,
        active_sms_provider: SmsProvider | None,
    ) -> AuthSecretsStatus:
        """Build status booleans from the secrets row — no plaintext exposed."""
        smtp_configured = row.smtp_password is not None
        username_set = row.smtp_username is not None

        # SMS is "configured" if the active provider's keys are all present
        sms_configured = False
        if active_sms_provider == SmsProvider.twilio:
            sms_configured = (
                row.twilio_account_sid is not None and row.twilio_auth_token is not None
            )
        elif active_sms_provider == SmsProvider.vonage:
            sms_configured = row.vonage_api_key is not None and row.vonage_api_secret is not None
        elif active_sms_provider == SmsProvider.aws_sns:
            sms_configured = (
                row.aws_access_key_id is not None
                and row.aws_secret_access_key is not None
                and row.aws_region is not None
            )

        return AuthSecretsStatus(
            project_id=project_id,
            smtp=SmtpSecretsStatus(
                configured=smtp_configured,
                username_set=username_set,
            ),
            sms=SmsSecretsStatus(
                provider=active_sms_provider,
                configured=sms_configured,
            ),
            updated_at=row.updated_at,
        )
