"""Outbound email and SMS (generated).

Routers depend on `get_mailer` / `get_sms_sender`, so tests (and your own code) can swap in
a different implementation with `app.dependency_overrides`. Network calls use the standard
library and run in a worker thread so they never block the event loop.
"""

from typing import Protocol

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


class UnconfiguredSmsSender:
    async def send(self, to: str, body: str) -> None:
        raise AppError("sms_not_configured", "sms delivery is not configured", 503)


def get_mailer() -> Mailer:
    return UnconfiguredMailer()


def get_sms_sender() -> SmsSender:
    return UnconfiguredSmsSender()
