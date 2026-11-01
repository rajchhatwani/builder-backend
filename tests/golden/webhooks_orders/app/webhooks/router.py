"""The webhook APIs (generated).

`router`         admin role only (default deny): subscriptions, secret rotation, delivery log, incoming secrets.
`public_router`  POST /webhooks/in/<endpoint>: no login, but nothing passes without a valid signature.

Secrets are shown once (creation, rotation) and never again; no route, log line or listing returns one."""

import datetime as _dt
import uuid
from typing import Any

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.auth.deps import CurrentPrincipal, require_roles
from app.core.errors import AppError, NotFoundError
from app.db import SessionDep
from app.models._base import utcnow
from app.providers.errors import VaultError
from app.webhooks import definitions, handlers, secrets, signing, ssrf
from app.webhooks.delivery import policy
from app.webhooks.models import ACTIVE, Attempt, Delivery, Endpoint, InboundSeen, Subscription

logger = structlog.get_logger()
MAX_SUBSCRIPTIONS = 50

router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"],
    dependencies=[Depends(require_roles(definitions.ADMIN_ROLE))],
)
public_router = APIRouter(prefix="/webhooks", tags=["webhooks-in"])


def _tenant(principal: CurrentPrincipal) -> uuid.UUID | None:
    """The tenant a row belongs to: the caller's in a multi-tenant project, None otherwise."""
    if not definitions.MULTI_TENANT:
        return None
    if principal.tenant_id is None:
        raise AppError("forbidden", "this account has no tenant", 403)
    return principal.tenant_id


def _scope(tenant: uuid.UUID | None) -> sa.ColumnElement[bool]:
    return Subscription.tenant_id.is_(None) if tenant is None else Subscription.tenant_id == tenant


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=ssrf.MAX_URL_LENGTH)
    event_types: list[str] = Field(min_length=1, max_length=len(definitions.EVENTS) or 1)
    description: str = Field(default="", max_length=200)


class SubscriptionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, min_length=1, max_length=ssrf.MAX_URL_LENGTH)
    event_types: list[str] | None = Field(default=None, min_length=1, max_length=len(definitions.EVENTS) or 1)
    description: str | None = Field(default=None, max_length=200)


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    url: str
    description: str
    event_types: list[str]
    status: str
    disabled_reason: str | None
    consecutive_failures: int
    secret_version: int
    rotating: bool
    created_at: _dt.datetime


class SubscriptionCreated(SubscriptionOut):
    secret: str = Field(description="Shown once. Store it now: it cannot be read again.")


class RotateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overlap_hours: int | None = Field(default=None, ge=1, le=720)


class DeliveryOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    last_status_code: int | None
    last_error: str | None
    created_at: _dt.datetime
    finished_at: _dt.datetime | None


class AttemptOut(BaseModel):
    attempt: int
    outcome: str
    status_code: int | None
    duration_ms: int
    created_at: _dt.datetime


class InboundSecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: SecretStr = Field(min_length=16, max_length=512)


class InboundOut(BaseModel):
    name: str
    has_secret: bool
    secret_version: int | None
    rotating: bool
    updated_at: _dt.datetime | None


def _out(sub: Subscription, now: _dt.datetime) -> dict[str, Any]:
    return {
        "id": sub.id,
        "url": sub.url,
        "description": sub.description,
        "event_types": list(sub.event_types),
        "status": sub.status,
        "disabled_reason": sub.disabled_reason,
        "consecutive_failures": sub.consecutive_failures,
        "secret_version": sub.secret_version,
        "rotating": len(secrets.live_versions(sub, now)) > 1,
        "created_at": sub.created_at,
    }


def _check_url(url: str) -> None:
    try:
        ssrf.parse_target(url, policy())
    except ssrf.Blocked as exc:
        raise AppError("url_not_allowed", f"this URL is not allowed ({exc.code})", 422) from None


def _check_events(names: list[str]) -> list[str]:
    unknown = sorted(set(names) - set(definitions.EVENTS))
    if unknown:
        raise AppError("unknown_event", "these events cannot be subscribed to: " + ", ".join(unknown[:5]), 422)
    return sorted(set(names))


async def _get(session: SessionDep, tenant: uuid.UUID | None, sub_id: uuid.UUID) -> Subscription:
    sub = (await session.execute(sa.select(Subscription).where(Subscription.id == sub_id, _scope(tenant)))).scalar_one_or_none()
    if sub is None:
        raise NotFoundError("subscription not found")
    return sub


def _vault_down() -> AppError:
    return AppError("vault_unavailable", "the credential vault is unavailable", 503)


@router.get("/events", response_model=list[str])
async def list_events() -> list[str]:
    return list(definitions.EVENTS)


@router.post("/subscriptions", response_model=SubscriptionCreated, status_code=201)
async def create_subscription(body: SubscriptionIn, session: SessionDep, principal: CurrentPrincipal) -> dict[str, Any]:
    tenant = _tenant(principal)
    _check_url(body.url)
    events = _check_events(body.event_types)
    count = (await session.execute(sa.select(sa.func.count()).select_from(Subscription).where(_scope(tenant)))).scalar_one()
    if count >= MAX_SUBSCRIPTIONS:
        raise AppError("too_many_subscriptions", f"at most {MAX_SUBSCRIPTIONS} subscriptions", 409)
    now = utcnow()
    sub = Subscription(
        id=uuid.uuid4(), tenant_id=tenant, url=body.url, description=body.description, event_types=events,
        status=ACTIVE, consecutive_failures=0, secret_version=1, created_by=principal.user_id, created_at=now, updated_at=now,
    )
    session.add(sub)
    await session.flush()
    secret = secrets.fresh_secret()
    try:
        await secrets.put(session, tenant, secrets.out_name(sub.id, 1), secret, principal.user_id)
    except VaultError:
        await session.rollback()
        raise _vault_down() from None
    await session.commit()
    logger.info("webhook_subscription_created", subscription_id=str(sub.id))
    return {**_out(sub, now), "secret": secret}


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(session: SessionDep, principal: CurrentPrincipal) -> list[dict[str, Any]]:
    tenant = _tenant(principal)
    rows = (await session.execute(sa.select(Subscription).where(_scope(tenant)).order_by(Subscription.created_at, Subscription.id))).scalars()
    now = utcnow()
    return [_out(s, now) for s in rows]


@router.get("/subscriptions/{sub_id}", response_model=SubscriptionOut)
async def get_subscription(sub_id: uuid.UUID, session: SessionDep, principal: CurrentPrincipal) -> dict[str, Any]:
    return _out(await _get(session, _tenant(principal), sub_id), utcnow())


@router.patch("/subscriptions/{sub_id}", response_model=SubscriptionOut)
async def update_subscription(sub_id: uuid.UUID, body: SubscriptionPatch, session: SessionDep, principal: CurrentPrincipal) -> dict[str, Any]:
    sub = await _get(session, _tenant(principal), sub_id)
    if body.url is not None:
        _check_url(body.url)
        sub.url = body.url
    if body.event_types is not None:
        sub.event_types = _check_events(body.event_types)
    if body.description is not None:
        sub.description = body.description
    sub.updated_at = utcnow()
    await session.commit()
    return _out(sub, utcnow())


@router.post("/subscriptions/{sub_id}/enable", response_model=SubscriptionOut)
async def enable_subscription(sub_id: uuid.UUID, session: SessionDep, principal: CurrentPrincipal) -> dict[str, Any]:
    sub = await _get(session, _tenant(principal), sub_id)
    sub.status, sub.disabled_reason, sub.consecutive_failures, sub.updated_at = ACTIVE, None, 0, utcnow()
    await session.commit()
    return _out(sub, utcnow())


@router.post("/subscriptions/{sub_id}/disable", response_model=SubscriptionOut)
async def disable_subscription(sub_id: uuid.UUID, session: SessionDep, principal: CurrentPrincipal) -> dict[str, Any]:
    sub = await _get(session, _tenant(principal), sub_id)
    sub.status, sub.disabled_reason, sub.updated_at = "disabled", "manual", utcnow()
    await session.commit()
    return _out(sub, utcnow())


@router.post("/subscriptions/{sub_id}/rotate", response_model=SubscriptionCreated)
async def rotate_subscription(sub_id: uuid.UUID, session: SessionDep, principal: CurrentPrincipal, body: RotateIn | None = None) -> dict[str, Any]:
    tenant = _tenant(principal)
    sub = await _get(session, tenant, sub_id)
    # lock the row so two rotations cannot pick the same next version
    await session.execute(sa.select(Subscription.id).where(Subscription.id == sub.id).with_for_update())
    await session.refresh(sub)
    hours = body.overlap_hours if body is not None and body.overlap_hours is not None else definitions.SECRET_OVERLAP_HOURS
    secret = secrets.fresh_secret()
    now = utcnow()
    try:
        await secrets.rotate(session, sub, tenant, lambda v: secrets.out_name(sub.id, v), secret, hours, now, principal.user_id)
    except VaultError:
        await session.rollback()
        raise _vault_down() from None
    sub.updated_at = now
    await session.commit()
    logger.info("webhook_secret_rotated", subscription_id=str(sub.id), version=sub.secret_version)
    return {**_out(sub, now), "secret": secret}


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def delete_subscription(sub_id: uuid.UUID, session: SessionDep, principal: CurrentPrincipal) -> Response:
    tenant = _tenant(principal)
    sub = await _get(session, tenant, sub_id)
    for version in {sub.secret_version, sub.previous_version} - {None}:
        await secrets.delete(session, tenant, secrets.out_name(sub.id, int(version)))  # type: ignore[arg-type]
    await session.delete(sub)
    await session.commit()
    return Response(status_code=204)


@router.get("/subscriptions/{sub_id}/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(sub_id: uuid.UUID, session: SessionDep, principal: CurrentPrincipal, limit: int = 50) -> list[Delivery]:
    sub = await _get(session, _tenant(principal), sub_id)
    stmt = sa.select(Delivery).where(Delivery.subscription_id == sub.id).order_by(Delivery.created_at.desc(), Delivery.id).limit(max(1, min(limit, 200)))
    return list((await session.execute(stmt)).scalars())


@router.get("/deliveries/{delivery_id}/attempts", response_model=list[AttemptOut])
async def list_attempts(delivery_id: uuid.UUID, session: SessionDep, principal: CurrentPrincipal) -> list[Attempt]:
    tenant = _tenant(principal)
    found = (
        await session.execute(
            sa.select(Delivery.id).join(Subscription, Subscription.id == Delivery.subscription_id).where(Delivery.id == delivery_id, _scope(tenant))
        )
    ).first()
    if found is None:
        raise NotFoundError("delivery not found")
    return list((await session.execute(sa.select(Attempt).where(Attempt.delivery_id == delivery_id).order_by(Attempt.attempt, Attempt.created_at))).scalars())


async def _endpoint(session: SessionDep, tenant: uuid.UUID | None, name: str) -> Endpoint | None:
    return (
        await session.execute(sa.select(Endpoint).where(Endpoint.tenant_id == secrets.tenant_key(tenant), Endpoint.name == name))
    ).scalar_one_or_none()


@router.get("/inbound", response_model=list[InboundOut])
async def list_inbound(session: SessionDep, principal: CurrentPrincipal) -> list[dict[str, Any]]:
    tenant = _tenant(principal)
    now = utcnow()
    out: list[dict[str, Any]] = []
    for name in definitions.INBOUND:
        row = await _endpoint(session, tenant, name)
        out.append({
            "name": name, "has_secret": row is not None,
            "secret_version": row.secret_version if row else None,
            "rotating": bool(row and len(secrets.live_versions(row, now)) > 1),
            "updated_at": row.updated_at if row else None,
        })
    return out


@router.put("/inbound/{name}/secret", response_model=InboundOut)
async def put_inbound_secret(name: str, body: InboundSecretIn, session: SessionDep, principal: CurrentPrincipal) -> dict[str, Any]:
    """Store the secret the sender signs with. Putting a new one rotates: the old one keeps working for the
    overlap window, so the sender can switch without a gap."""
    if name not in definitions.INBOUND:
        raise NotFoundError("unknown incoming endpoint")
    tenant = _tenant(principal)
    now = utcnow()
    value = body.value.get_secret_value()
    try:
        row = await _endpoint(session, tenant, name)
        if row is None:
            await secrets.put(session, tenant, secrets.in_name(name, 1), value, principal.user_id)
            row = Endpoint(tenant_id=secrets.tenant_key(tenant), name=name, secret_version=1, updated_at=now)
            session.add(row)
        else:
            await session.execute(sa.select(Endpoint.name).where(Endpoint.tenant_id == row.tenant_id, Endpoint.name == name).with_for_update())
            await session.refresh(row)
            await secrets.rotate(session, row, tenant, lambda v: secrets.in_name(name, v), value, definitions.SECRET_OVERLAP_HOURS, now, principal.user_id)
            row.updated_at = now
    except VaultError:
        await session.rollback()
        raise _vault_down() from None
    await session.commit()
    return {"name": name, "has_secret": True, "secret_version": row.secret_version, "rotating": len(secrets.live_versions(row, now)) > 1, "updated_at": row.updated_at}


# --- incoming ---------------------------------------------------------------------------------------------


def _unauthorized() -> AppError:
    return AppError("invalid_signature", "the request is not signed correctly", 401)


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and not (declared.isascii() and declared.isdigit()):
        raise AppError("bad_request", "invalid Content-Length", 400)
    if declared is not None and int(declared) > limit:
        raise AppError("payload_too_large", "the body is too large", 413)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise AppError("payload_too_large", "the body is too large", 413)
        chunks.append(chunk)
    return b"".join(chunks)


async def receive(name: str, tenant: uuid.UUID | None, request: Request, session: SessionDep, now: _dt.datetime | None = None) -> dict[str, str]:
    """Verify the raw body, refuse replays and duplicates, then run the project's handler."""
    cfg = definitions.INBOUND.get(name)
    if cfg is None:
        raise NotFoundError("unknown incoming endpoint")
    body = await _read_body(request, cfg["max_body_bytes"])
    stamp = now or utcnow()
    delivery_id = request.headers.get(signing.HEADER_ID)
    row = await _endpoint(session, tenant, name)
    candidates: list[str] = []
    if row is not None:
        try:
            for version in secrets.live_versions(row, stamp):
                value = await secrets.get(session, tenant, secrets.in_name(name, version))
                if value is not None:
                    candidates.append(value)
        except VaultError:
            raise _vault_down() from None
    # No secret stored, no signature header, a bad or stale signature: all the same answer (fail closed).
    if not signing.verify(
        request.headers.get(signing.HEADER_SIGNATURE),
        delivery_id,
        request.headers.get(signing.HEADER_TIMESTAMP),
        body,
        candidates,
        tolerance_seconds=cfg["tolerance_seconds"],
        now=stamp.timestamp(),
    ):
        logger.warning("webhook_in_rejected", endpoint=name)
        raise _unauthorized()
    assert delivery_id is not None
    first = (
        await session.execute(
            pg_insert(InboundSeen)
            .values(tenant_id=secrets.tenant_key(tenant), endpoint=name, delivery_id=delivery_id, received_at=stamp)
            .on_conflict_do_nothing()
            .returning(InboundSeen.delivery_id)
        )
    ).scalar_one_or_none()
    if first is None:
        await session.rollback()
        return {"status": "duplicate"}
    handlers.load_handlers()
    fn = handlers.get(name)
    if fn is not None:
        try:
            await fn(handlers.InboundContext(endpoint=name, tenant_id=tenant, delivery_id=delivery_id, body=body, session=session))
        except Exception as exc:
            await session.rollback()  # nothing is recorded: the sender's retry runs the handler again
            logger.error("webhook_in_handler_failed", endpoint=name, error=type(exc).__name__)
            raise AppError("handler_failed", "the handler failed", 500) from None
    await session.commit()
    return {"status": "accepted"}


if definitions.MULTI_TENANT:

    @public_router.post("/in/{name}/{tenant_id}", status_code=200)
    async def receive_for_tenant(name: str, tenant_id: uuid.UUID, request: Request, session: SessionDep) -> dict[str, str]:
        return await receive(name, tenant_id, request, session)

else:

    @public_router.post("/in/{name}", status_code=200)
    async def receive_webhook(name: str, request: Request, session: SessionDep) -> dict[str, str]:
        return await receive(name, None, request, session)
