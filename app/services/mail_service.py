"""Platform e-mail (org invitations) over SMTP, with the standard library only.

Best effort by design: an invitation is valid whether or not the e-mail goes out, and the
admin always gets the link once in the API response. Failures are logged without the
recipient's link or any credentials.
"""

import asyncio
import smtplib
from email.message import EmailMessage

import structlog

from app.config import get_settings

log = structlog.get_logger()


def mail_configured() -> bool:
    return get_settings().smtp_host is not None


def _send_sync(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    assert settings.smtp_host is not None
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = " ".join(subject.split())  # an org name may hold a newline
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password is not None:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)


async def send(to: str, subject: str, body: str) -> bool:
    """True when handed to the SMTP server; False when not configured or it failed."""
    if not mail_configured():
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, body)
    except (OSError, ValueError, smtplib.SMTPException) as exc:
        log.warning("mail_send_failed", error=type(exc).__name__)
        return False
    return True


async def send_invitation(*, to: str, org_name: str, inviter: str, url: str) -> bool:
    body = (
        f"{inviter} invited you to join {org_name} on Backend Builder.\n\n"
        f"Accept the invitation: {url}\n\n"
        "The link works once and expires in 14 days. If you didn't expect this, ignore it.\n"
    )
    return await send(to, f"You're invited to {org_name}", body)
