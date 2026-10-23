"""HTTP routes of the payments module (generated).

Everything here is deny-by-default: a role list that is empty in the settings means nobody may call
the route. The webhook route is the one unauthenticated entry; it trusts nothing until the
provider's signature has been verified.
"""

import ipaddress
import uuid
from typing import Annotated

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.core.errors import NotFoundError
from app.core.pagination import Page, PageParams, page_params
from app.db import SessionDep, session_factory
from app.payments import audit, config, events, idempotency, jobs, service, state
from app.payments.models import Dispute, Job, Payment, Refund, WebhookEvent
from app.payments.providers import get_provider
from app.payments.providers.base import ProviderUnavailable, WebhookRejected
from app.payments.schemas import (
    AuditVerification,
    DisputeRead,
    JobRead,
    OpsStatus,
    PaymentCreate,
    PaymentRead,
    RefundCreate,
    RefundRead,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/payments", tags=["payments"])
_PAGE = Depends(page_params(20, 100))
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


def _payment_read(payment: Payment, user: AuthUser) -> PaymentRead:
    """The checkout link is for the person paying, and only while they still have to pay: staff
    who can see the payment do not get a link they could pay (or hand on) with."""
    read = PaymentRead.model_validate(payment)
    if payment.status != state.REQUIRES_PAYMENT or payment.created_by_id != user.id:
        read.checkout_url = None
    return read


# --- payments -----------------------------------------------------------------------------


@router.post("", response_model=PaymentRead, status_code=201, summary="Start a payment")
async def create_payment(
    body: PaymentCreate, session: SessionDep, user: CurrentUser, idempotency_key: IdempotencyKey = None
) -> PaymentRead:
    """Send the user to `checkout_url` to pay. Repeat a request with the same Idempotency-Key and
    the same body and you get the same payment back, never a second one."""
    payment = await service.create_payment(
        session,
        user,
        payable_id=body.payable_id,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
        idempotency_key=idempotency.validate_key(idempotency_key),
    )
    return _payment_read(payment, user)


@router.get("", response_model=Page[PaymentRead], summary="List payments")
async def list_payments(
    session: SessionDep,
    user: CurrentUser,
    page: Annotated[PageParams, _PAGE],
    status: Annotated[str | None, Query(max_length=20)] = None,
    payable_id: uuid.UUID | None = None,
) -> Page[PaymentRead]:
    sees_all = service.has_role(user, "read_all")
    if not sees_all:
        service.require_role(user, "read")
    conditions = [*service._in_tenant(user)]
    if not sees_all:
        conditions.append(Payment.created_by_id == user.id)
    if status:
        conditions.append(Payment.status == status)
    if payable_id:
        conditions.append(Payment.payable_id == payable_id)
    total = (await session.execute(sa.select(sa.func.count()).select_from(Payment).where(*conditions))).scalar_one()
    rows = (
        await session.execute(
            sa.select(Payment)
            .where(*conditions)
            .order_by(Payment.created_at.desc(), Payment.id)
            .limit(page.limit)
            .offset(page.offset)
        )
    ).scalars()
    return Page[PaymentRead](
        items=[_payment_read(p, user) for p in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/{payment_id}", response_model=PaymentRead, summary="Get a payment")
async def get_payment(payment_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> PaymentRead:
    return _payment_read(await service.get_payment(session, user, payment_id), user)


@router.post("/{payment_id}/cancel", response_model=PaymentRead, summary="Abandon an unpaid checkout")
async def cancel_payment(payment_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> PaymentRead:
    return _payment_read(await service.cancel_payment(session, user, payment_id), user)


# --- refunds and disputes --------------------------------------------------------------------


@router.post("/{payment_id}/refunds", response_model=RefundRead, status_code=201, summary="Refund a payment")
async def create_refund(
    payment_id: uuid.UUID,
    body: RefundCreate,
    session: SessionDep,
    user: CurrentUser,
    idempotency_key: IdempotencyKey = None,
) -> RefundRead:
    refund = await service.request_refund(
        session,
        user,
        payment_id,
        amount_minor=body.amount_minor,
        reason=body.reason,
        idempotency_key=idempotency.validate_key(idempotency_key),
    )
    return RefundRead.model_validate(refund)


@router.get("/{payment_id}/refunds", response_model=list[RefundRead], summary="Refunds of a payment")
async def list_payment_refunds(payment_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> list[RefundRead]:
    payment = await service.get_payment(session, user, payment_id)
    rows = (
        await session.execute(
            sa.select(Refund).where(Refund.payment_id == payment.id).order_by(Refund.created_at, Refund.id)
        )
    ).scalars()
    return [RefundRead.model_validate(r) for r in rows]


@router.post("/refunds/{refund_id}/approve", response_model=RefundRead, summary="Approve a refund")
async def approve_refund(refund_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> RefundRead:
    return RefundRead.model_validate(await service.decide_refund(session, user, refund_id, approve=True))


@router.post("/refunds/{refund_id}/reject", response_model=RefundRead, summary="Reject a refund")
async def reject_refund(refund_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> RefundRead:
    return RefundRead.model_validate(await service.decide_refund(session, user, refund_id, approve=False))


@router.get("/{payment_id}/disputes", response_model=list[DisputeRead], summary="Disputes of a payment")
async def list_payment_disputes(payment_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> list[DisputeRead]:
    payment = await service.get_payment(session, user, payment_id, staff=service.has_role(user, "refund"))
    rows = (
        await session.execute(
            sa.select(Dispute).where(Dispute.payment_id == payment.id).order_by(Dispute.created_at)
        )
    ).scalars()
    return [DisputeRead.model_validate(d) for d in rows]


# --- operations (queue, audit) -----------------------------------------------------------------


@router.get("/ops/status", response_model=OpsStatus, summary="Queue and event health")
async def ops_status(session: SessionDep, user: CurrentUser) -> OpsStatus:
    service.require_role(user, "operate")
    failed = (
        await session.execute(
            sa.select(sa.func.count()).select_from(WebhookEvent).where(WebhookEvent.status == events.FAILED)
        )
    ).scalar_one()
    unprocessed = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(WebhookEvent)
            .where(WebhookEvent.status.in_((events.RECEIVED, events.PROCESSING)))
        )
    ).scalar_one()
    return OpsStatus(queue=await jobs.queue_stats(session), events_failed=failed, events_unprocessed=unprocessed)


@router.get("/ops/dead-jobs", response_model=list[JobRead], summary="Jobs that gave up")
async def dead_jobs(session: SessionDep, user: CurrentUser) -> list[JobRead]:
    service.require_role(user, "operate")
    rows = (
        await session.execute(
            sa.select(Job).where(Job.status == jobs.DEAD).order_by(Job.updated_at.desc()).limit(100)
        )
    ).scalars()
    return [JobRead.model_validate(j) for j in rows]


@router.post("/ops/dead-jobs/{job_id}/retry", status_code=202, summary="Run a dead job again")
async def retry_dead_job(job_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> dict[str, bool]:
    service.require_role(user, "operate")
    ok = await jobs.retry_dead(session, job_id)
    if ok:
        await audit.append(
            session,
            payment_id=None,
            event="dead_job_retried",
            data={"job_id": str(job_id)},
            actor_type=audit.ACTOR_USER,
            actor_id=user.id,
            tenant_id=service.tenant_of(user),
        )
    await session.commit()
    if not ok:
        raise NotFoundError("no such dead job")
    return {"queued": True}


@router.get(
    "/ops/audit/{payment_id}/verify", response_model=AuditVerification, summary="Check the audit chain"
)
async def verify_audit(payment_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> AuditVerification:
    service.require_role(user, "operate")
    await service.get_payment(session, user, payment_id, staff=True)
    intact, bad = await audit.verify_chain(session, payment_id)
    return AuditVerification(intact=intact, first_bad_sequence=bad)


# --- webhook ----------------------------------------------------------------------------------

_GENERIC_REJECTION = {"code": "invalid_webhook", "message": "the webhook could not be accepted"}


def _client_ip(request: Request) -> str | None:
    settings = config.get_payments_settings()
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    if settings.payments_trusted_proxies and len(hops) >= settings.payments_trusted_proxies:
        return hops[-settings.payments_trusted_proxies]
    return request.client.host if request.client else None


def _ip_allowed(request: Request) -> bool:
    if not config.WEBHOOK_IP_ALLOWLIST_ENABLED:
        return True
    ip = _client_ip(request)
    if ip is None:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in network for network in config.get_payments_settings().webhook_networks())


async def _read_capped_body(request: Request) -> bytes | None:
    """The request body, or None if it is larger than the cap (never reads more than cap + 1)."""
    limit = config.WEBHOOK_MAX_BODY_BYTES
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/webhooks/{provider_name}", include_in_schema=False)
async def receive_webhook(provider_name: str, request: Request) -> Response:
    if provider_name != config.PROVIDER:
        raise NotFoundError("not found")
    reject = JSONResponse(_GENERIC_REJECTION, status_code=400)
    if not _ip_allowed(request):
        logger.warning("webhook_rejected", reason="ip_not_allowed")
        return reject
    body = await _read_capped_body(request)
    if body is None:
        logger.warning("webhook_rejected", reason="body_too_large")
        return JSONResponse(_GENERIC_REJECTION, status_code=413)
    try:
        event = get_provider().verify_webhook(body, request.headers)
    except WebhookRejected as exc:
        logger.warning("webhook_rejected", reason=exc.reason)
        return reject
    async with session_factory() as session:
        event_pk, is_new = await events.store_event(session, provider_name, event, body)
        status = await events.event_status(session, event_pk)
        if status in (events.PROCESSED, events.IGNORED):
            await session.commit()
            return JSONResponse({"received": True})
        queued = config.get_payments_settings().payments_webhook_mode == "queued"
        if queued:
            await jobs.enqueue(
                session, jobs.PROCESS_EVENT, {"event_id": str(event_pk)}, dedupe_key=f"event:{event_pk}"
            )
        await session.commit()
        if queued:
            return JSONResponse({"received": True})
        try:
            await events.process_event(session, event_pk)
        except (events.EventRetry, ProviderUnavailable):
            return JSONResponse({"code": "try_again"}, status_code=503)
        except Exception:
            logger.exception("webhook_processing_failed", event_id=event.event_id)
            return JSONResponse({"code": "processing_failed"}, status_code=500)
    return JSONResponse({"received": True})

