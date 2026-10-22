"""SQLAlchemy model for project auth secrets.

Stores credentials (SMTP password, Twilio / Vonage / AWS keys) encrypted at
rest using Fernet (AES-128-CBC + HMAC-SHA256 via app.core.crypto).

Design decisions:
  - Separate table from ProjectAuthConfig so that routine config reads never
    touch the secrets rows.
  - 1:1 with ProjectAuthConfig (and therefore 1:1 with Project).
  - All secret columns are TEXT (ciphertext). None = not configured.
  - No plaintext ever written; the service layer encrypts before INSERT/UPDATE
    and decrypts only at generation time.
"""

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectAuthSecrets(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Encrypted credential store for a project's auth integrations."""

    __tablename__ = "project_auth_secrets"

    # 1:1 with project_auth_configs (which is 1:1 with projects)
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # ── SMTP ──────────────────────────────────────────────────────────────────
    # Most providers (SendGrid, Mailgun, SES SMTP) use the API key as the
    # SMTP password.  Username is optional — some providers require it.
    smtp_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_password: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Twilio ────────────────────────────────────────────────────────────────
    twilio_account_sid: Mapped[str | None] = mapped_column(Text, nullable=True)
    twilio_auth_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Vonage (Nexmo) ───────────────────────────────────────────────────────
    vonage_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    vonage_api_secret: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── AWS SNS ───────────────────────────────────────────────────────────────
    aws_access_key_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    aws_secret_access_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    aws_region: Mapped[str | None] = mapped_column(Text, nullable=True)
