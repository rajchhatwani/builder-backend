"""Payment logic (generated): create, cancel, refund, and apply what the provider reports.

Principles that hold throughout:
  * the amount always comes from the payable row on the server, never from the client;
  * a database transaction never stays open while we wait for the provider;
  * every state change is an atomic guarded UPDATE, so racing processes cannot go backwards;
  * the provider's own report (fetched from its API) is the truth, a webhook is only a hint;
  * every change writes an audit entry in the same transaction.
"""

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthUser
from app.auth.service import effective_roles
from app.core.errors import AppError, ConflictError, NotFoundError
from app.payments import audit, config, idempotency, jobs, payable, state
from app.payments.models import Dispute, Payment, Refund
from app.payments.money import normalise_currency, to_minor
from app.payments.providers import get_provider
from app.payments.providers.base import (
    CheckoutRequest,
    ProviderCheckout,
    ProviderDispute,
    ProviderRefund,
    ProviderRejected,
    ProviderUnavailable,
    RefundRequest,
)

logger = structlog.get_logger()

# Stripe wants a Checkout Session to live at least 30 minutes and the expiry must not change when
# the same creation is retried, so it is derived from created_at and retries stop after 4 minutes.
CHECKOUT_LIFETIME = timedelta(minutes=35)
CREATE_RETRY_WINDOW = timedelta(minutes=4)
REFUND_REASONS = ("requested_by_customer", "duplicate", "fraudulent")


# --- access ---------------------------------------------------------------------------


def has_role(user: AuthUser, key: str) -> bool:
    return bool(effective_roles(user.roles) & set(config.ROLES.get(key, ())))


def require_role(user: AuthUser, key: str) -> None:
    if not has_role(user, key):  # an empty role list for `key` means nobody: fail closed
        raise AppError("forbidden", "you do not have permission to do that", 403)


def tenant_of(user: AuthUser) -> uuid.UUID | None:
    return getattr(user, "tenant_id", None) if config.MULTI_TENANT else None


def _in_tenant(user: AuthUser) -> list[sa.ColumnElement[bool]]:
    return [Payment.tenant_id == tenant_of(user)] if config.MULTI_TENANT else []


async def get_payment(
    session: AsyncSession, user: AuthUser, payment_id: uuid.UUID, *, staff: bool = False
) -> Payment:
    """A payment the user may see: their own, or any in their tenant with read_all (or `staff`
    for the roles that manage refunds). Anything else is reported as not found."""
    conditions = [Payment.id == payment_id, *_in_tenant(user)]
    sees_all = staff or has_role(user, "read_all")
    if not sees_all:
        require_role(user, "read")
        conditions.append(Payment.created_by_id == user.id)
    payment = (await session.execute(sa.select(Payment).where(*conditions))).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("payment not found")
    return payment


async def _lock_payment(session: AsyncSession, payment_id: uuid.UUID) -> Payment:
    payment = (
        await session.execute(
            sa.select(Payment)
            .where(Payment.id == payment_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("payment not found")
    return payment


def safe_checkout_url(url: str | None, *, production: bool) -> bool:
    """The page we send the payer to must exist and, in production, be https."""
    if not url:
        return False
    return url.startswith("https://") or (not production and url.startswith("http://"))


def _pick_url(value: str | None, allowed: tuple[str, ...], name: str) -> str:
    """Only an exact entry of the allowlist is accepted: there is no open redirect."""
    if value is None:
        return allowed[0]
    if value not in allowed:
        raise AppError("invalid_url", f"{name} is not one of the allowed URLs", 422)
    return value


# --- creating a payment -----------------------------------------------------------------


async def create_payment(
    session: AsyncSession,
    user: AuthUser,
    *,
    payable_id: uuid.UUID,
    success_url: str | None,
    cancel_url: str | None,
    idempotency_key: str,
) -> Payment:
    require_role(user, "create")
    success = _pick_url(success_url, config.SUCCESS_URLS, "success_url")
    cancel = _pick_url(cancel_url, config.CANCEL_URLS, "cancel_url")
    scope = idempotency.scope_hash(tenant_of(user), user.id, "POST /payments", idempotency_key)
    claim = await idempotency.claim(
        session,
        scope=scope,
        req_hash=idempotency.request_hash(
            {"payable_id": str(payable_id), "success_url": success, "cancel_url": cancel}
        ),
        resource_type="payment",
    )
    if not claim.fresh and claim.resource_id is not None:
        await session.commit()  # nothing to undo; a rollback would expire the caller's `user`
        existing = await session.get(Payment, claim.resource_id)
        if existing is None or existing.created_by_id != user.id:
            raise NotFoundError("payment not found")
        return await finish_payment(session, existing.id)

    item = await payable.load_for_payer(session, user, payable_id)
    if item.status != payable.PENDING:
        raise ConflictError("this item cannot be paid for in its current state")
    currency = normalise_currency(item.currency)
    amount_minor = to_minor(item.amount, currency)
    payment = Payment(
        id=uuid.uuid4(),
        tenant_id=tenant_of(user),
        created_by_id=user.id,
        provider=config.PROVIDER,
        livemode=config.get_payments_settings().livemode,
        status=state.CREATING,
        payable_id=item.id,
        amount_minor=amount_minor,
        currency=currency,
        success_url=success,
        cancel_url=cancel,
        refunded_minor=0,
        refund_reserved_minor=0,
    )
    session.add(payment)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise AppError(
            "payment_in_progress",
            "this item already has a payment in progress or completed",
            409,
        ) from None
    await audit.append(
        session,
        payment_id=payment.id,
        event="payment_created",
        data={"amount_minor": amount_minor, "currency": currency, "payable_id": str(item.id)},
        actor_type=audit.ACTOR_USER,
        actor_id=user.id,
        tenant_id=payment.tenant_id,
    )
    await idempotency.attach(session, scope, payment.id)
    await session.commit()
    return await finish_payment(session, payment.id)


async def finish_payment(session: AsyncSession, payment_id: uuid.UUID) -> Payment:
    """Create the provider checkout for a payment that has none yet. Safe to call repeatedly:
    the provider call carries a key derived from the payment id, so it happens once."""
    payment = (
        await session.execute(
            sa.select(Payment).where(Payment.id == payment_id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    if payment.status != state.CREATING:
        return payment
    now = datetime.now(UTC)
    if now > payment.created_at + CREATE_RETRY_WINDOW:
        await _fail_creating(session, payment, "creation_timeout")
        raise AppError("payment_failed", "the payment could not be started; try again", 502)
    request = CheckoutRequest(
        payment_id=str(payment.id),
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        description=f"Payment {str(payment.payable_id)[:8]}",
        success_url=payment.success_url,
        cancel_url=payment.cancel_url,
        expires_at=payment.created_at + CHECKOUT_LIFETIME,
        idempotency_key=f"pay_{payment.id}",
    )
    try:
        checkout = await get_provider().create_checkout(request)
    except ProviderUnavailable as exc:
        logger.warning("checkout_unavailable", payment_id=str(payment.id), code=exc.code)
        await jobs.enqueue(
            session,
            jobs.FINISH_PAYMENT,
            {"payment_id": str(payment.id)},
            run_at=now + timedelta(seconds=15),
            dedupe_key=f"finish:{payment.id}",
        )
        await session.commit()
        raise AppError("provider_unavailable", "the payment service is unavailable; retry", 502) from None
    except ProviderRejected as exc:
        await _fail_creating(session, payment, exc.code)
        raise AppError("payment_rejected", "the payment service refused this payment", 422) from None

    if (
        checkout.amount_minor != payment.amount_minor
        or checkout.currency != payment.currency
        or checkout.livemode != payment.livemode
        or not safe_checkout_url(checkout.url, production=config.get_payments_settings().production)
    ):
        logger.error("checkout_mismatch", payment_id=str(payment.id))
        await _fail_creating(session, payment, "provider_mismatch")
        raise AppError("payment_failed", "the payment could not be started", 502)

    moved = await session.execute(
        sa.update(Payment)
        .where(Payment.id == payment.id, Payment.status == state.CREATING)
        .values(
            status=state.REQUIRES_PAYMENT,
            provider_session_id=checkout.session_id,
            provider_payment_intent_id=checkout.payment_intent_id,
            checkout_url=checkout.url,
            expires_at=request.expires_at,
            updated_at=now,
        )
    )
    if moved.rowcount:  # type: ignore[attr-defined]
        await audit.append(
            session,
            payment_id=payment.id,
            event="checkout_created",
            data={"expires_at": request.expires_at.isoformat()},
            tenant_id=payment.tenant_id,
        )
    await session.commit()
    return (
        await session.execute(
            sa.select(Payment).where(Payment.id == payment.id).execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _fail_creating(session: AsyncSession, payment: Payment, code: str) -> None:
    moved = await session.execute(
        sa.update(Payment)
        .where(Payment.id == payment.id, Payment.status == state.CREATING)
        .values(status=state.FAILED, failure_code=code[:64], updated_at=datetime.now(UTC))
    )
    if moved.rowcount:  # type: ignore[attr-defined]
        await audit.append(
            session,
            payment_id=payment.id,
            event="payment_failed",
            data={"code": code[:64]},
            tenant_id=payment.tenant_id,
        )
    await session.commit()


# --- cancelling ------------------------------------------------------------------------


async def cancel_payment(session: AsyncSession, user: AuthUser, payment_id: uuid.UUID) -> Payment:
    """The payer (or an operator) abandons a checkout that has not been paid."""
    payment = await get_payment(session, user, payment_id, staff=has_role(user, "operate"))
    if payment.created_by_id != user.id and not has_role(user, "operate"):
        raise NotFoundError("payment not found")
    if payment.status != state.REQUIRES_PAYMENT or payment.provider_session_id is None:
        raise ConflictError("only a payment that is waiting for the payer can be cancelled")
    provider = get_provider()
    try:
        checkout = await provider.expire_checkout(payment.provider_session_id)
    except ProviderRejected:
        # Already completed or expired at the provider: learn the real state, then say so.
        checkout = await provider.retrieve_checkout(payment.provider_session_id)
        await sync_payment_from_checkout(session, payment.id, checkout)
        raise ConflictError("this payment can no longer be cancelled") from None
    except ProviderUnavailable:
        raise AppError("provider_unavailable", "the payment service is unavailable; retry", 502) from None
    if checkout.paid:
        await sync_payment_from_checkout(session, payment.id, checkout)
        raise ConflictError("this payment was already paid")
    locked = await _lock_payment(session, payment.id)
    moved = await session.execute(
        sa.update(Payment)
        .where(Payment.id == payment.id, Payment.status == state.REQUIRES_PAYMENT)
        .values(status=state.CANCELED, updated_at=datetime.now(UTC))
    )
    if moved.rowcount:  # type: ignore[attr-defined]
        await audit.append(
            session,
            payment_id=payment.id,
            event="payment_canceled",
            actor_type=audit.ACTOR_USER,
            actor_id=user.id,
            tenant_id=locked.tenant_id,
        )
    await session.commit()
    return await get_payment(session, user, payment_id, staff=True)


# --- applying the provider's report -------------------------------------------------------


def _target_status(checkout: ProviderCheckout, hint: str | None) -> str | None:
    if checkout.paid:
        return state.SUCCEEDED
    if hint == "failed":
        return state.FAILED
    if checkout.payment_pending:
        return state.PROCESSING
    if checkout.status == "expired":
        return state.EXPIRED
    return None


async def sync_payment_from_checkout(
    session: AsyncSession,
    payment_id: uuid.UUID,
    checkout: ProviderCheckout,
    *,
    hint: str | None = None,
    actor_type: str = audit.ACTOR_PROVIDER,
) -> bool:
    """Move the payment to what the provider reports. Returns True if anything changed."""
    payment = await _lock_payment(session, payment_id)
    now = datetime.now(UTC)
    payment.last_synced_at = now
    if (
        checkout.amount_minor != payment.amount_minor
        or checkout.currency != payment.currency
        or checkout.livemode != payment.livemode
        or (checkout.payment_id is not None and checkout.payment_id != str(payment.id))
    ):
        # Never mark money as received when the provider's numbers differ from ours.
        logger.error("provider_mismatch", payment_id=str(payment.id))
        await audit.append(
            session,
            payment_id=payment.id,
            event="provider_mismatch",
            data={"provider_amount_minor": checkout.amount_minor, "ours": payment.amount_minor},
            actor_type=actor_type,
            tenant_id=payment.tenant_id,
        )
        await session.commit()
        return False
    changed = False
    if payment.provider_session_id is None:
        payment.provider_session_id = checkout.session_id
        changed = True
    if checkout.payment_intent_id and payment.provider_payment_intent_id is None:
        payment.provider_payment_intent_id = checkout.payment_intent_id
        changed = True
    target = _target_status(checkout, hint)
    if target is not None and target != payment.status:
        if state.can_move(state.PAYMENT_TRANSITIONS, payment.status, target):
            changed |= await _apply_payment_status(session, payment, target, actor_type)
    await session.commit()
    return changed


async def _apply_payment_status(
    session: AsyncSession, payment: Payment, target: str, actor_type: str
) -> bool:
    before = payment.status
    values: dict[str, object] = {"status": target, "updated_at": datetime.now(UTC)}
    if target == state.SUCCEEDED:
        values["succeeded_at"] = datetime.now(UTC)
    nested = await session.begin_nested()
    try:
        moved = await session.execute(
            sa.update(Payment)
            .where(Payment.id == payment.id, Payment.status.in_(state.sources_for(state.PAYMENT_TRANSITIONS, target)))
            .values(**values)
        )
        await session.flush()
    except IntegrityError:
        # Another payment for the same item is active: money was taken twice. Keep the facts.
        await nested.rollback()
        logger.error("duplicate_charge", payment_id=str(payment.id))
        await audit.append(
            session,
            payment_id=payment.id,
            event="duplicate_charge",
            data={"status": before},
            actor_type=actor_type,
            tenant_id=payment.tenant_id,
        )
        return True
    await nested.commit()
    if not moved.rowcount:  # type: ignore[attr-defined]
        return False
    await session.refresh(payment)
    await audit.append(
        session,
        payment_id=payment.id,
        event=f"payment_{target}",
        data={"from": before},
        actor_type=actor_type,
        tenant_id=payment.tenant_id,
    )
    if target == state.SUCCEEDED:
        moved_payable = await payable.move_status(
            session, payment.payable_id, (payable.PENDING,), payable.PAID
        )
        if not moved_payable:
            logger.error("payable_not_pending", payment_id=str(payment.id))
            await audit.append(
                session,
                payment_id=payment.id,
                event="payable_status_conflict",
                data={"wanted": payable.PAID},
                actor_type=actor_type,
                tenant_id=payment.tenant_id,
            )
    return True


# --- refunds ---------------------------------------------------------------------------


async def request_refund(
    session: AsyncSession,
    user: AuthUser,
    payment_id: uuid.UUID,
    *,
    amount_minor: int | None,
    reason: str,
    idempotency_key: str,
) -> Refund:
    require_role(user, "refund")
    if reason not in REFUND_REASONS:
        raise AppError("invalid_reason", f"reason must be one of {', '.join(REFUND_REASONS)}", 422)
    await get_payment(session, user, payment_id, staff=True)  # tenant check, 404 if foreign
    scope = idempotency.scope_hash(
        tenant_of(user), user.id, f"POST /payments/{payment_id}/refunds", idempotency_key
    )
    claim = await idempotency.claim(
        session,
        scope=scope,
        req_hash=idempotency.request_hash(
            {"payment": str(payment_id), "amount_minor": amount_minor, "reason": reason}
        ),
        resource_type="refund",
    )
    if not claim.fresh and claim.resource_id is not None:
        await session.commit()  # see create_payment
        existing = await session.get(Refund, claim.resource_id)
        if existing is None:
            raise NotFoundError("refund not found")
        return existing

    payment = await _lock_payment(session, payment_id)
    if payment.status != state.SUCCEEDED:
        raise ConflictError("only a completed payment can be refunded")
    remaining = payment.amount_minor - payment.refund_reserved_minor
    amount = remaining if amount_minor is None else amount_minor
    if amount < 1 or amount > remaining:
        raise AppError(
            "refund_exceeds_payment",
            "the refund is larger than what is left to refund on this payment",
            422,
        )
    threshold = config.REFUND_APPROVAL_THRESHOLD_MINOR
    needs_approval = threshold is not None and amount > threshold
    refund = Refund(
        id=uuid.uuid4(),
        payment_id=payment.id,
        tenant_id=payment.tenant_id,
        amount_minor=amount,
        currency=payment.currency,
        status=state.PENDING_APPROVAL if needs_approval else state.REQUESTED,
        reason=reason,
        source="api",
        requested_by_id=user.id,
        attempts=0,
    )
    session.add(refund)
    await session.flush()
    await _recompute_refund_totals(session, payment)
    await audit.append(
        session,
        payment_id=payment.id,
        event="refund_requested",
        data={"refund_id": str(refund.id), "amount_minor": amount, "needs_approval": needs_approval},
        actor_type=audit.ACTOR_USER,
        actor_id=user.id,
        tenant_id=payment.tenant_id,
    )
    await idempotency.attach(session, scope, refund.id)
    if not needs_approval:
        await jobs.enqueue(
            session, jobs.DISPATCH_REFUND, {"refund_id": str(refund.id)}, dedupe_key=f"refund:{refund.id}"
        )
    await session.commit()
    if not needs_approval:
        await _try_dispatch(session, refund.id)
    return await _reload_refund(session, refund.id)


async def decide_refund(
    session: AsyncSession, user: AuthUser, refund_id: uuid.UUID, *, approve: bool
) -> Refund:
    """The second person: approve or reject a refund that needs it. Never your own request."""
    require_role(user, "approve_refund")
    refund = await _reload_refund(session, refund_id)
    payment = await get_payment(session, user, refund.payment_id, staff=True)
    payment = await _lock_payment(session, payment.id)
    refund = await _reload_refund(session, refund_id)
    if refund.status != state.PENDING_APPROVAL:
        raise ConflictError("this refund is not waiting for approval")
    if refund.requested_by_id == user.id:
        raise AppError("cannot_approve_own_refund", "a different person must decide this refund", 403)
    target = state.REQUESTED if approve else state.REJECTED
    refund.status = target
    refund.approved_by_id = user.id
    refund.approved_at = datetime.now(UTC)
    await session.flush()
    await _recompute_refund_totals(session, payment)
    await audit.append(
        session,
        payment_id=payment.id,
        event="refund_approved" if approve else "refund_rejected",
        data={"refund_id": str(refund.id)},
        actor_type=audit.ACTOR_USER,
        actor_id=user.id,
        tenant_id=payment.tenant_id,
    )
    if approve:
        await jobs.enqueue(
            session, jobs.DISPATCH_REFUND, {"refund_id": str(refund.id)}, dedupe_key=f"refund:{refund.id}"
        )
    await session.commit()
    if approve:
        await _try_dispatch(session, refund.id)
    return await _reload_refund(session, refund_id)


async def _try_dispatch(session: AsyncSession, refund_id: uuid.UUID) -> None:
    """Send a refund to the provider right away; on any failure the queued job will retry."""
    try:
        await dispatch_refund(session, refund_id)
    except (ProviderUnavailable, AppError):
        await session.rollback()


async def _reload_refund(session: AsyncSession, refund_id: uuid.UUID) -> Refund:
    refund = (
        await session.execute(
            sa.select(Refund).where(Refund.id == refund_id).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if refund is None:
        raise NotFoundError("refund not found")
    return refund


async def dispatch_refund(session: AsyncSession, refund_id: uuid.UUID) -> None:
    """Send an approved refund to the provider. Exactly one process wins the claim; the provider
    call carries a key derived from the refund id, so a repeat can never refund twice."""
    claimed = (
        await session.execute(
            sa.text(
                """
                UPDATE pay_refunds SET status = 'submitting', attempts = attempts + 1,
                       locked_until = now() + make_interval(secs => :lease), updated_at = now()
                WHERE id = :id AND (status = 'requested' OR (status = 'submitting' AND locked_until < now()))
                RETURNING id
                """
            ),
            {"id": refund_id, "lease": float(config.get_payments_settings().payments_job_lease_seconds)},
        )
    ).first()
    await session.commit()
    if claimed is None:
        return
    refund = await _reload_refund(session, refund_id)
    payment = (await session.execute(sa.select(Payment).where(Payment.id == refund.payment_id))).scalar_one()
    if payment.provider_payment_intent_id is None:
        await _release_refund(session, refund, "no_payment_intent")
        raise AppError("refund_not_ready", "the payment has no provider reference yet", 409)
    try:
        result = await get_provider().create_refund(
            RefundRequest(
                refund_id=str(refund.id),
                payment_intent_id=payment.provider_payment_intent_id,
                amount_minor=refund.amount_minor,
                reason=refund.reason,
                idempotency_key=f"refund_{refund.id}",
            )
        )
    except ProviderUnavailable as exc:
        await _release_refund(session, refund, exc.code)
        raise
    except ProviderRejected as exc:
        await _finish_refund(session, refund.id, state.REFUND_FAILED, exc.code)
        return
    await apply_provider_refund(session, payment.id, result, our_refund_id=refund.id)


async def _release_refund(session: AsyncSession, refund: Refund, code: str) -> None:
    await session.execute(
        sa.update(Refund)
        .where(Refund.id == refund.id, Refund.status == state.SUBMITTING)
        .values(status=state.REQUESTED, failure_code=code[:64])
    )
    await session.commit()


async def _finish_refund(session: AsyncSession, refund_id: uuid.UUID, target: str, code: str | None) -> None:
    refund = await _reload_refund(session, refund_id)
    payment = await _lock_payment(session, refund.payment_id)
    refund = await _reload_refund(session, refund_id)
    if state.can_move(state.REFUND_TRANSITIONS, refund.status, target):
        refund.status = target
        refund.failure_code = code[:64] if code else None
        await session.flush()
        await _recompute_refund_totals(session, payment)
        await audit.append(
            session,
            payment_id=payment.id,
            event=f"refund_{target}",
            data={"refund_id": str(refund.id), "code": code},
            tenant_id=payment.tenant_id,
        )
        await _update_payable_after_refund(session, payment)
    await session.commit()


async def apply_provider_refund(
    session: AsyncSession,
    payment_id: uuid.UUID,
    reported: ProviderRefund,
    *,
    our_refund_id: uuid.UUID | None = None,
) -> None:
    """Record what the provider says about a refund (ours, or one made in its dashboard)."""
    payment = await _lock_payment(session, payment_id)
    if reported.currency != payment.currency:
        logger.error("refund_currency_mismatch", payment_id=str(payment.id))
        await session.commit()
        return
    refund = (
        await session.execute(
            sa.select(Refund).where(Refund.provider_refund_id == reported.refund_id).with_for_update()
        )
    ).scalar_one_or_none()
    if refund is None and our_refund_id is not None:
        refund = (
            await session.execute(
                sa.select(Refund).where(Refund.id == our_refund_id, Refund.payment_id == payment.id).with_for_update()
            )
        ).scalar_one_or_none()
    if refund is None and reported.our_refund_id:
        try:
            wanted = uuid.UUID(reported.our_refund_id)
        except ValueError:
            wanted = None
        if wanted is not None:
            refund = (
                await session.execute(
                    sa.select(Refund).where(Refund.id == wanted, Refund.payment_id == payment.id).with_for_update()
                )
            ).scalar_one_or_none()
    created = False
    if refund is None:
        # Made outside this system (the provider's dashboard): record it, it is real money.
        refund = Refund(
            id=uuid.uuid4(),
            payment_id=payment.id,
            tenant_id=payment.tenant_id,
            amount_minor=reported.amount_minor,
            currency=payment.currency,
            status=reported.status,
            reason="provider",
            source="provider",
            attempts=0,
        )
        session.add(refund)
        created = True
    else:
        if refund.provider_refund_id is None:
            refund.provider_refund_id = reported.refund_id
        if refund.amount_minor != reported.amount_minor:
            logger.error("refund_amount_mismatch", refund_id=str(refund.id))
        target = reported.status
        # A request we sent ("submitting") becomes whatever the provider reports.
        if target != refund.status and state.can_move(state.REFUND_TRANSITIONS, refund.status, target):
            refund.status = target
            refund.failure_code = reported.failure_code
    if created:
        refund.provider_refund_id = reported.refund_id
    await session.flush()
    await _recompute_refund_totals(session, payment)
    await audit.append(
        session,
        payment_id=payment.id,
        event="refund_recorded" if created else f"refund_{refund.status}",
        data={"refund_id": str(refund.id), "amount_minor": reported.amount_minor, "status": refund.status},
        actor_type=audit.ACTOR_PROVIDER,
        tenant_id=payment.tenant_id,
    )
    await _update_payable_after_refund(session, payment)
    await session.commit()


async def _recompute_refund_totals(session: AsyncSession, payment: Payment) -> None:
    """Rebuild the refund totals from the refunds themselves, so they can never drift."""
    reserved, refunded = (
        await session.execute(
            sa.select(
                sa.func.coalesce(
                    sa.func.sum(Refund.amount_minor).filter(Refund.status.in_(state.REFUND_RESERVING_STATES)), 0
                ),
                sa.func.coalesce(
                    sa.func.sum(Refund.amount_minor).filter(Refund.status == state.REFUND_SUCCEEDED), 0
                ),
            ).where(Refund.payment_id == payment.id)
        )
    ).one()
    payment.refund_reserved_minor = int(reserved)
    payment.refunded_minor = int(refunded)
    await session.flush()


async def _update_payable_after_refund(session: AsyncSession, payment: Payment) -> None:
    if payment.refunded_minor >= payment.amount_minor:
        await payable.move_status(
            session, payment.payable_id, (payable.PAID, payable.PARTIALLY_REFUNDED), payable.REFUNDED
        )
    elif payment.refunded_minor > 0:
        await payable.move_status(
            session, payment.payable_id, (payable.PAID,), payable.PARTIALLY_REFUNDED
        )


# --- disputes ----------------------------------------------------------------------------


async def apply_dispute(session: AsyncSession, payment_id: uuid.UUID, reported: ProviderDispute) -> None:
    payment = await _lock_payment(session, payment_id)
    dispute = (
        await session.execute(
            sa.select(Dispute).where(Dispute.provider_dispute_id == reported.dispute_id).with_for_update()
        )
    ).scalar_one_or_none()
    closed = reported.status in (state.DISPUTE_WON, state.DISPUTE_LOST, state.DISPUTE_CLOSED)
    now = datetime.now(UTC)
    if dispute is None:
        dispute = Dispute(
            id=uuid.uuid4(),
            payment_id=payment.id,
            tenant_id=payment.tenant_id,
            provider_dispute_id=reported.dispute_id,
            status=reported.status,
            reason=reported.reason,
            amount_minor=reported.amount_minor,
            currency=payment.currency,
            evidence_due_by=reported.evidence_due_by,
            opened_at=reported.created or now,
            closed_at=now if closed else None,
        )
        session.add(dispute)
        event = "dispute_opened"
    else:
        event = "dispute_updated"
        if dispute.status == reported.status:
            await session.commit()
            return
        dispute.status = reported.status
        dispute.evidence_due_by = reported.evidence_due_by
        dispute.closed_at = now if closed else None
    await session.flush()
    await audit.append(
        session,
        payment_id=payment.id,
        event=event,
        data={"dispute_id": str(dispute.id), "status": reported.status, "amount_minor": reported.amount_minor},
        actor_type=audit.ACTOR_PROVIDER,
        tenant_id=payment.tenant_id,
    )
    if event == "dispute_opened":
        logger.warning("dispute_opened", payment_id=str(payment.id), tenant_id=str(payment.tenant_id))
    await session.commit()
