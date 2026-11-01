"""The notifications API (generated).

  GET    /notifications/types                                  the declared types (any signed-in user)
  GET    /notifications/preferences                            my settings per type and channel
  PUT    /notifications/preferences/{type}/{channel}           opt in / out (optional types only)
  GET    /notifications/templates                              effective templates     (admin role)
  PUT    /notifications/templates/{type}/{channel}             override a template     (admin role)
  DELETE /notifications/templates/{type}/{channel}             back to the default     (admin role)
  POST   /notifications/templates/{type}/{channel}/preview     render with sample data (admin role)
  GET    /notifications/deliveries                             the delivery log        (admin role)

Everything is limited to the caller's tenant. The delivery log never shows an address or a body."""

import datetime as _dt
import uuid
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CurrentPrincipal, require_roles
from app.core.errors import AppError, NotFoundError
from app.db import SessionDep
from app.notifications import definitions, render, service
from app.notifications.models import STATUSES, NotificationDelivery

router = APIRouter(prefix="/notifications", tags=["notifications"])
admin = Depends(require_roles(definitions.ADMIN_ROLE))

Channel = Literal["email", "sms", "push"]


class TypeOut(BaseModel):
    name: str
    category: Literal["transactional", "optional"]
    channels: list[str]
    variables: list[str]


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(default="", max_length=200, description="Email subject / push title (one line); empty for SMS.")
    body: str = Field(max_length=200_000, description="Text with {{ variable }} placeholders of the type's variables only.")
    html: bool = Field(default=False, description="Email only: the body is HTML and every value is HTML-escaped.")


class TemplateOut(BaseModel):
    type: str
    channel: str
    subject: str
    body: str
    html: bool
    source: Literal["default", "custom"]
    variables: list[str]
    updated_at: _dt.datetime | None


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, max_length=200, description="Draft subject; omit to use the current one.")
    body: str | None = Field(default=None, max_length=200_000, description="Draft body; omit to use the current one.")
    html: bool | None = None
    variables: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, description="Sample values; declared variables left out show as [name]."
    )


class PreviewOut(BaseModel):
    subject: str
    body: str
    html: bool


class PreferenceOut(BaseModel):
    type: str
    channel: str
    category: Literal["transactional", "optional"]
    enabled: bool
    editable: bool


class PreferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class DeliveryOut(BaseModel):
    id: uuid.UUID
    type: str
    channel: str
    recipient_key: str
    recipient_hint: str
    status: str
    reason: str | None
    attempts: int
    provider: str | None
    provider_message_id: str | None
    error_code: str | None
    source_event_id: uuid.UUID | None
    created_at: _dt.datetime
    finished_at: _dt.datetime | None


def _tenant(principal: CurrentPrincipal) -> uuid.UUID:
    return principal.tenant_id or service.NIL_TENANT


def _check(type_name: str, channel: str) -> None:
    try:
        service.channel_def(type_name, channel)
    except service.UnknownNotification:
        raise NotFoundError("unknown notification type or channel") from None


def _out(tpl: service.Template) -> TemplateOut:
    return TemplateOut(
        type=tpl.type, channel=tpl.channel, subject=tpl.subject, body=tpl.body, html=tpl.html,
        source="custom" if tpl.source == "custom" else "default",
        variables=sorted(service.variables_of(tpl.type)), updated_at=tpl.updated_at,
    )


@router.get("/types", response_model=list[TypeOut], summary="The notification types of this project")
async def list_types(_: CurrentPrincipal) -> list[TypeOut]:
    return [
        TypeOut(name=n, category=d["category"], channels=list(d["channels"]), variables=list(d["variables"]))
        for n, d in sorted(definitions.TYPES.items())
    ]


@router.get("/preferences", response_model=list[PreferenceOut], summary="My notification settings")
async def my_preferences(session: SessionDep, principal: CurrentPrincipal) -> list[PreferenceOut]:
    return [PreferenceOut(**p) for p in await service.preferences_of(session, _tenant(principal), str(principal.user_id))]


@router.put(
    "/preferences/{type_name}/{channel}", response_model=PreferenceOut,
    summary="Opt in or out of one type on one channel",
)
async def set_my_preference(
    type_name: str, channel: Channel, body: PreferenceIn, session: SessionDep, principal: CurrentPrincipal
) -> PreferenceOut:
    _check(type_name, channel)
    if not service.optional(type_name):
        raise AppError("not_optional", "this notification is required and cannot be switched off", 409)
    await service.set_preference(session, _tenant(principal), str(principal.user_id), type_name, channel, body.enabled)
    await session.commit()
    return PreferenceOut(
        type=type_name, channel=channel, category="optional", enabled=body.enabled, editable=True
    )


@router.get("/templates", response_model=list[TemplateOut], dependencies=[admin], summary="Effective templates")
async def list_templates(session: SessionDep, principal: CurrentPrincipal) -> list[TemplateOut]:
    out: list[TemplateOut] = []
    for name in sorted(definitions.TYPES):
        for channel in definitions.TYPES[name]["channels"]:
            out.append(_out(await service.effective_template(session, _tenant(principal), name, channel)))
    return out


@router.put(
    "/templates/{type_name}/{channel}", response_model=TemplateOut, dependencies=[admin],
    summary="Override the template of one type and channel for this tenant",
)
async def put_template(
    type_name: str, channel: Channel, body: TemplateIn, session: SessionDep, principal: CurrentPrincipal
) -> TemplateOut:
    _check(type_name, channel)
    try:
        tpl = await service.save_template(
            session, _tenant(principal), type_name, channel, body.subject, body.body, body.html, principal.user_id
        )
    except render.RenderError as exc:
        raise AppError("invalid_template", str(exc), 422) from None
    await session.commit()
    return _out(tpl)


@router.delete(
    "/templates/{type_name}/{channel}", status_code=204, dependencies=[admin],
    summary="Remove this tenant's override (the default applies again)",
)
async def delete_template(type_name: str, channel: Channel, session: SessionDep, principal: CurrentPrincipal) -> Response:
    _check(type_name, channel)
    if not await service.delete_template(session, _tenant(principal), type_name, channel):
        raise NotFoundError("this template has no override")
    await session.commit()
    return Response(status_code=204)


@router.post(
    "/templates/{type_name}/{channel}/preview", response_model=PreviewOut, dependencies=[admin],
    summary="Render a template with sample data (nothing is sent or saved)",
)
async def preview_template(
    type_name: str, channel: Channel, body: PreviewIn, session: SessionDep, principal: CurrentPrincipal
) -> PreviewOut:
    _check(type_name, channel)
    current = await service.effective_template(session, _tenant(principal), type_name, channel)
    subject = current.subject if body.subject is None else body.subject
    text = current.body if body.body is None else body.body
    html = current.html if body.html is None else body.html
    try:
        service.validate_template(type_name, channel, subject, text, html)
        values = {**service.sample_values(type_name), **body.variables}
        shown = service.Template(type_name, channel, subject, text, html, "default", None)
        rendered_subject, rendered_body = service.render_template(shown, values)
    except render.RenderError as exc:
        raise AppError("invalid_template", str(exc), 422) from None
    return PreviewOut(subject=rendered_subject, body=rendered_body, html=html and channel == "email")


@router.get("/deliveries", response_model=list[DeliveryOut], dependencies=[admin], summary="The delivery log")
async def list_deliveries(
    session: SessionDep,
    principal: CurrentPrincipal,
    status: Annotated[str | None, Query(description="queued | processing | sent | failed | suppressed")] = None,
    type: Annotated[str | None, Query(description="Notification type name")] = None,  # noqa: A002
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[DeliveryOut]:
    if type is not None and ("\x00" in type or len(type) > 40):
        raise AppError("validation_error", "unknown type", 422)
    if status is not None and status not in STATUSES:
        raise AppError("validation_error", "unknown status", 422)
    stmt = sa.select(NotificationDelivery).where(NotificationDelivery.tenant_id == _tenant(principal))
    if status is not None:
        stmt = stmt.where(NotificationDelivery.status == status)
    if type is not None:
        stmt = stmt.where(NotificationDelivery.type == type)
    stmt = stmt.order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars()
    return [
        DeliveryOut(
            id=r.id, type=r.type, channel=r.channel, recipient_key=r.recipient_key, recipient_hint=r.recipient_hint,
            status=r.status, reason=r.reason, attempts=r.attempts, provider=r.provider,
            provider_message_id=r.provider_message_id, error_code=r.error_code, source_event_id=r.source_event_id,
            created_at=r.created_at, finished_at=r.finished_at,
        )
        for r in rows
    ]
