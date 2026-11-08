"""Sending, templates and preferences (generated). The only place that decides whether a message goes out.

Default deny: an unknown type or channel raises; an optional message needs the user's setting (or the
type's default) to say yes; an address that fails the strict check is logged as suppressed, never sent."""

import datetime as _dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import utcnow
from app.notifications import definitions, render
from app.notifications.models import (
    QUEUED,
    SUPPRESSED,
    NotificationDelivery,
    NotificationPreference,
    NotificationTemplate,
)

logger = structlog.get_logger("notifications")

NIL_TENANT = uuid.UUID(int=0)  # the tenant of a project that is not multi-tenant
CHANNELS = ("email", "sms", "push")


class UnknownNotification(ValueError):
    """The notification type or channel is not declared in the spec."""


@dataclass(frozen=True)
class Recipient:
    """Who gets it. `key` identifies the person for their preferences (a user id as text); the addresses
    are per channel. A channel without an address is logged as suppressed (`no_address`)."""

    key: str
    email: str | None = None
    phone: str | None = None
    device: str | None = None

    def address(self, channel: str) -> str | None:
        return {"email": self.email, "sms": self.phone, "push": self.device}.get(channel)


@dataclass(frozen=True)
class Template:
    type: str
    channel: str
    subject: str
    body: str
    html: bool
    source: str  # default | custom
    updated_at: _dt.datetime | None


def type_def(type_name: str) -> dict[str, Any]:
    declared = definitions.TYPES.get(type_name)
    if declared is None:
        raise UnknownNotification("unknown notification type")
    return declared  # type: ignore[no-any-return]


def channel_def(type_name: str, channel: str) -> dict[str, Any]:
    declared = type_def(type_name)
    if channel not in declared["channels"]:
        raise UnknownNotification("this type is not sent on that channel")
    return declared


def variables_of(type_name: str) -> frozenset[str]:
    return frozenset(type_def(type_name)["variables"])


# --- templates ---------------------------------------------------------------------------------


def default_template(type_name: str, channel: str) -> Template:
    declared = channel_def(type_name, channel)
    tpl = declared["templates"][channel]
    return Template(type_name, channel, tpl["subject"], tpl["body"], bool(tpl["html"]), "default", None)


async def effective_template(session: AsyncSession, tenant_id: uuid.UUID, type_name: str, channel: str) -> Template:
    default = default_template(type_name, channel)
    row = (
        await session.execute(
            sa.select(NotificationTemplate).where(
                NotificationTemplate.tenant_id == tenant_id,
                NotificationTemplate.type == type_name,
                NotificationTemplate.channel == channel,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return default
    return Template(type_name, channel, row.subject, row.body, row.html, "custom", row.updated_at)


def validate_template(type_name: str, channel: str, subject: str, body: str, html: bool) -> None:
    """Raise render.RenderError unless this is a well-formed template for the type and channel."""
    channel_def(type_name, channel)
    variables = variables_of(type_name)
    limits = render.LIMITS[channel]
    if "\x00" in subject or "\x00" in body:
        raise render.RenderError("a template must not contain a NUL character")
    if html and channel != "email":
        raise render.RenderError("html applies to email only")
    if not body.strip():
        raise render.RenderError("the body must not be empty")
    if len(body) > limits["body"] or len(subject) > limits["subject"]:
        raise render.RenderError("the template is too long")
    if channel == "sms" and subject:
        raise render.RenderError("an SMS has no subject")
    if channel in ("email", "push") and not subject.strip():
        raise render.RenderError("a subject / title is required")
    if any(ch in subject for ch in "\r\n\0"):
        raise render.RenderError("a subject is one line")
    render.check_template(subject, variables)
    render.check_template(body, variables)


async def save_template(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    type_name: str,
    channel: str,
    subject: str,
    body: str,
    html: bool,
    user_id: uuid.UUID | None,
) -> Template:
    validate_template(type_name, channel, subject, body, html)
    now = utcnow()
    await session.execute(
        pg_insert(NotificationTemplate)
        .values(
            id=uuid.uuid4(), tenant_id=tenant_id, type=type_name, channel=channel,
            subject=subject, body=body, html=html, updated_at=now, updated_by=user_id,
        )
        .on_conflict_do_update(
            constraint="uq_nt_templates_key",
            set_={"subject": subject, "body": body, "html": html, "updated_at": now, "updated_by": user_id},
        )
    )
    return Template(type_name, channel, subject, body, html, "custom", now)


async def delete_template(session: AsyncSession, tenant_id: uuid.UUID, type_name: str, channel: str) -> bool:
    channel_def(type_name, channel)
    result = await session.execute(
        sa.delete(NotificationTemplate).where(
            NotificationTemplate.tenant_id == tenant_id,
            NotificationTemplate.type == type_name,
            NotificationTemplate.channel == channel,
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def sample_values(type_name: str) -> dict[str, str]:
    return {name: f"[{name}]" for name in type_def(type_name)["variables"]}


def render_template(tpl: Template, values: Mapping[str, object]) -> tuple[str, str]:
    cleaned = render.clean_values(values, variables_of(tpl.type))
    return render.render(tpl.channel, tpl.subject, tpl.body, tpl.html, cleaned)


# --- preferences -------------------------------------------------------------------------------


def optional(type_name: str) -> bool:
    return type_def(type_name)["category"] == "optional"


async def preference(session: AsyncSession, tenant_id: uuid.UUID, user_key: str, type_name: str, channel: str) -> bool:
    """Whether this user wants this type on this channel. Transactional types are always wanted."""
    declared = channel_def(type_name, channel)
    if declared["category"] != "optional":
        return True
    row = (
        await session.execute(
            sa.select(NotificationPreference.enabled).where(
                NotificationPreference.tenant_id == tenant_id,
                NotificationPreference.user_key == user_key,
                NotificationPreference.type == type_name,
                NotificationPreference.channel == channel,
            )
        )
    ).scalar_one_or_none()
    return bool(declared["default_enabled"]) if row is None else bool(row)


async def set_preference(
    session: AsyncSession, tenant_id: uuid.UUID, user_key: str, type_name: str, channel: str, enabled: bool
) -> None:
    channel_def(type_name, channel)
    if not optional(type_name):
        raise UnknownNotification("a transactional notification cannot be switched off")
    await session.execute(
        pg_insert(NotificationPreference)
        .values(
            id=uuid.uuid4(), tenant_id=tenant_id, user_key=user_key, type=type_name,
            channel=channel, enabled=enabled, updated_at=utcnow(),
        )
        .on_conflict_do_update(
            constraint="uq_nt_preferences_key", set_={"enabled": enabled, "updated_at": utcnow()}
        )
    )


async def preferences_of(session: AsyncSession, tenant_id: uuid.UUID, user_key: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            sa.select(NotificationPreference).where(
                NotificationPreference.tenant_id == tenant_id, NotificationPreference.user_key == user_key
            )
        )
    ).scalars()
    chosen = {(r.type, r.channel): r.enabled for r in rows}
    out: list[dict[str, Any]] = []
    for name in sorted(definitions.TYPES):
        declared = definitions.TYPES[name]
        for channel in declared["channels"]:
            is_optional = declared["category"] == "optional"
            out.append(
                {
                    "type": name,
                    "channel": channel,
                    "category": declared["category"],
                    "editable": is_optional,
                    "enabled": chosen.get((name, channel), declared["default_enabled"]) if is_optional else True,
                }
            )
    return out


# --- sending -----------------------------------------------------------------------------------


async def _log(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    type_name: str,
    channel: str,
    recipient: Recipient,
    status: str,
    reason: str | None,
    address: str | None,
    variables: dict[str, str] | None,
    event_id: uuid.UUID | None,
    dedupe_key: str | None,
) -> uuid.UUID | None:
    """Add one delivery row; None when `dedupe_key` was already used (the message already exists)."""
    now = utcnow()
    values = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "type": type_name,
        "channel": channel,
        "recipient_key": recipient.key[:200],
        "recipient_hint": render.mask(channel, address),
        "status": status,
        "reason": reason,
        "attempts": 0,
        "source_event_id": event_id,
        "dedupe_key": dedupe_key,
        "address": address if status == QUEUED else None,
        "variables": variables if status == QUEUED else None,
        "next_attempt_at": now,
        "created_at": now,
        "finished_at": None if status == QUEUED else now,
    }
    stmt = pg_insert(NotificationDelivery).values(**values).on_conflict_do_nothing().returning(NotificationDelivery.id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def notify(
    session: AsyncSession,
    type_name: str,
    recipient: Recipient,
    variables: Mapping[str, object] | None = None,
    *,
    tenant_id: uuid.UUID | None = None,
    channels: tuple[str, ...] | None = None,
    event_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> list[uuid.UUID]:
    """Queue `type_name` for `recipient` on each of the type's channels (or the subset `channels`).

    Part of the caller's transaction (the caller commits). Returns the ids of the rows created. A channel
    the person opted out of, has no valid address for, or that is already queued under `dedupe_key`
    creates a suppressed row or nothing; this never sends. Raises UnknownNotification for a type or
    channel that is not declared and render.RenderError for bad variables (programmer errors)."""
    declared = type_def(type_name)
    wanted = channels if channels is not None else tuple(declared["channels"])
    for channel in wanted:
        channel_def(type_name, channel)
    if dedupe_key is not None and not 0 < len(dedupe_key) <= 150:
        raise ValueError("dedupe_key is 1 to 150 characters")
    if not recipient.key or len(recipient.key) > 200 or "\x00" in recipient.key:
        raise ValueError("recipient.key is 1 to 200 characters, without NUL")
    if dedupe_key is not None and "\x00" in dedupe_key:
        raise ValueError("dedupe_key must not contain NUL")
    tenant = tenant_id or NIL_TENANT
    cleaned = render.clean_values(variables or {}, variables_of(type_name))
    created: list[uuid.UUID] = []
    for channel in wanted:
        address = recipient.address(channel)
        key = f"{dedupe_key}:{channel}" if dedupe_key is not None else None
        status, reason = QUEUED, None
        if not render.valid_address(channel, address):
            status, reason = SUPPRESSED, "no_address" if not address else "invalid_address"
        elif not await preference(session, tenant, recipient.key, type_name, channel):
            status, reason = SUPPRESSED, "opt_out"
        row = await _log(
            session, tenant_id=tenant, type_name=type_name, channel=channel, recipient=recipient,
            status=status, reason=reason, address=address, variables=cleaned,
            event_id=event_id, dedupe_key=key,
        )
        if row is not None:
            created.append(row)
        logger.info(
            "notification_queued", type=type_name, channel=channel, tenant=str(tenant), status=status,
            reason=reason, duplicate=row is None,
        )
    return created
