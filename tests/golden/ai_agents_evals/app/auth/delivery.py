"""Outbound email and SMS (generated).

Routers depend on `get_mailer` / `get_sms_sender`, so tests (and your own code) can swap in
a different implementation with `app.dependency_overrides`. Network calls use the standard
library and run in a worker thread so they never block the event loop.
"""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from app.auth import config
from app.core.errors import AppError

_TIMEOUT_SECONDS = 10


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmsSender(Protocol):
    async def send(self, to: str, body: str) -> None: ...


class DeliveryError(Exception):
    """A message could not be handed to the provider."""


class SmtpMailer:
    """Sends plain-text mail through the SMTP server configured at generation time."""

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send, to, subject, body)

    @staticmethod
    def _send(to: str, subject: str, body: str) -> None:
        settings = config.get_auth_settings()
        message = EmailMessage()
        message["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_FROM_EMAIL}>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        context = ssl.create_default_context()
        try:
            if config.SMTP_PORT == 465:
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    config.SMTP_HOST, config.SMTP_PORT, timeout=_TIMEOUT_SECONDS, context=context
                )
            else:
                client = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=_TIMEOUT_SECONDS)
            with client:
                if config.SMTP_USE_TLS and config.SMTP_PORT != 465:
                    client.starttls(context=context)
                if settings.smtp_username and settings.smtp_password:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise DeliveryError(f"smtp delivery failed: {type(exc).__name__}") from exc


class UnconfiguredMailer:
    async def send(self, to: str, subject: str, body: str) -> None:
        raise AppError("email_not_configured", "email delivery is not configured", 503)


class UnconfiguredSmsSender:
    async def send(self, to: str, body: str) -> None:
        raise AppError("sms_not_configured", "sms delivery is not configured", 503)


def get_mailer() -> Mailer:
    return SmtpMailer()


def get_sms_sender() -> SmsSender:
    return UnconfiguredSmsSender()
