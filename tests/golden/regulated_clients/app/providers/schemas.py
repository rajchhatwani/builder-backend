"""Typed request and response models per adapter kind (generated). Bodies are never logged."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KINDS = ("email", "sms", "push", "payments", "storage", "llm", "generic")
Kind = Literal["email", "sms", "push", "payments", "storage", "llm", "generic"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailRequest(_Model):
    to: str = Field(max_length=320)
    subject: str = Field(max_length=998)
    body: str = Field(max_length=200_000)


class SmsRequest(_Model):
    to: str = Field(max_length=32)
    body: str = Field(max_length=1600)


class PushRequest(_Model):
    device: str = Field(max_length=512)
    title: str = Field(max_length=200)
    body: str = Field(max_length=4000)


class PaymentsRequest(_Model):
    action: str = Field(max_length=40)
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    reference: str = Field(max_length=200)


class StorageRequest(_Model):
    action: Literal["put", "get", "delete"]
    key: str = Field(max_length=1024)
    content_type: str | None = Field(default=None, max_length=200)
    size: int = Field(default=0, ge=0)


class LlmRequest(_Model):
    prompt: str = Field(max_length=200_000)
    max_tokens: int = Field(default=256, ge=1, le=100_000)


class GenericRequest(_Model):
    operation: str = Field(max_length=100)
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class SendResult(_Model):
    """What every adapter returns: an id the provider gave the message, and whether it took it."""

    message_id: str
    accepted: bool = True


class HealthStatus(_Model):
    ok: bool
    detail: str = ""


REQUESTS: dict[str, type[BaseModel]] = {
    "email": EmailRequest,
    "sms": SmsRequest,
    "push": PushRequest,
    "payments": PaymentsRequest,
    "storage": StorageRequest,
    "llm": LlmRequest,
    "generic": GenericRequest,
}
