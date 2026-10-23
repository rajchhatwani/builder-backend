"""Outbound email and SMS (generated).

Routers depend on `get_mailer` / `get_sms_sender`, so tests (and your own code) can swap in
a different implementation with `app.dependency_overrides`. Network calls use the standard
library and run in a worker thread so they never block the event loop.
"""

import asyncio
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


class UnconfiguredMailer:
    async def send(self, to: str, subject: str, body: str) -> None:
        raise AppError("email_not_configured", "email delivery is not configured", 503)


class SnsSender:
    async def send(self, to: str, body: str) -> None:
        await asyncio.to_thread(self._send, to, body)

    @staticmethod
    def _send(to: str, body: str) -> None:
        import boto3  # imported here so the rest of the app works without AWS configured
        from botocore.exceptions import BotoCoreError, ClientError

        settings = config.get_auth_settings()
        client = boto3.client("sns", region_name=settings.aws_region)
        attributes = {
            "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}
        }
        if not config.SMS_FROM.startswith("+"):
            attributes["AWS.SNS.SMS.SenderID"] = {
                "DataType": "String",
                "StringValue": config.SMS_FROM,
            }
        try:
            client.publish(PhoneNumber=to, Message=body, MessageAttributes=attributes)
        except (BotoCoreError, ClientError) as exc:
            raise DeliveryError(f"sns delivery failed: {type(exc).__name__}") from exc


def get_mailer() -> Mailer:
    return UnconfiguredMailer()


def get_sms_sender() -> SmsSender:
    return SnsSender()
