"""Razorpay adapter (generated): hosted Payment Links, refunds, disputes and signed webhooks.

Checkout is a Razorpay Payment Link: the payer opens its hosted page and pays there, so card data
never reaches this code and no JavaScript is needed in your frontend. Only the standard library
talks to Razorpay (urllib, hmac). Every request has a timeout, TLS is verified, responses are
size-capped, retries happen only for calls that are safe to repeat, and nothing the provider says
in prose is passed on.

Differences from Stripe that matter here:
  * a Payment Link has no creation idempotency key; its `reference_id` (our payment id) must be
    unique, so a repeated creation is recovered by looking the link up by that reference;
  * webhooks carry no timestamp, so replay protection is the unique event id plus the rule that a
    webhook is only a hint (the object is fetched before anything changes);
  * entities do not say whether they are test or live: the mode follows from the API key.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import structlog

from app.payments import config
from app.payments.providers.base import (
    CheckoutRequest,
    ProviderCheckout,
    ProviderDispute,
    ProviderEvent,
    ProviderRefund,
    ProviderRejected,
    ProviderUnavailable,
    RefundRequest,
    WebhookRejected,
)

logger = structlog.get_logger()

_MAX_RESPONSE_BYTES = 1_048_576
_RETRIES = 2
_ID_RE = re.compile(r"[A-Za-z0-9_]{3,64}")
_EVENT_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,255}")
_SIGNATURE_RE = re.compile(r"[0-9a-fA-F]{64}")

# Razorpay event name -> (kind, hint). Kinds are the provider-neutral vocabulary events.py
# understands. Failed individual payment attempts are ignored on purpose: the payment link stays
# open and the payer can try again; only the link ending (paid, expired, cancelled) matters.
_EVENT_KINDS: dict[str, tuple[str, str | None]] = {
    "payment_link.paid": ("checkout", None),
    "payment_link.partially_paid": ("checkout", None),
    "payment_link.expired": ("checkout", None),
    "payment_link.cancelled": ("checkout", None),
    "refund.created": ("refund", None),
    "refund.processed": ("refund", None),
    "refund.failed": ("refund", None),
    "refund.speed_changed": ("refund", None),
    "payment.dispute.created": ("dispute", None),
    "payment.dispute.won": ("dispute", None),
    "payment.dispute.lost": ("dispute", None),
    "payment.dispute.closed": ("dispute", None),
    "payment.dispute.under_review": ("dispute", None),
    "payment.dispute.action_required": ("dispute", None),
}
_REFUND_STATUS = {"pending": "pending", "processed": "succeeded", "failed": "failed"}
_DISPUTE_STATUS = {
    "open": "open",
    "under_review": "under_review",
    "won": "won",
    "lost": "lost",
    "closed": "closed",
}
_LINK_STATUS = {
    "created": "open",
    "partially_paid": "open",
    "paid": "complete",
    "expired": "expired",
    "cancelled": "expired",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A provider API never needs to redirect, and following a redirect could carry our credentials
    to another host (urllib keeps the Authorization header), so a redirect is simply an error."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _safe_id(value: Any) -> str | None:
    return value if isinstance(value, str) and _ID_RE.fullmatch(value) else None


def _scalar(value: Any) -> str | int | bool | None:
    if isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        return value[:255]
    return None


def _timestamp(value: Any) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if isinstance(value, int) and value > 0 else None


def _uuid_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


class RazorpayProvider:
    name = "razorpay"

    def __init__(self, settings: config.PaymentsSettings | None = None) -> None:
        self._fixed_settings = settings

    @property
    def _settings(self) -> config.PaymentsSettings:
        # Looked up on every use, so a reloaded configuration (a rotated secret) takes effect.
        return self._fixed_settings or config.get_payments_settings()

    # --- HTTP -----------------------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        *,
        repeatable: bool | None = None,
    ) -> dict[str, Any]:
        settings = self._settings
        url = settings.api_base.rstrip("/") + path
        credentials = f"{settings.public_key()}:{settings.secret_key()}".encode()
        headers = {
            "Authorization": "Basic " + base64.b64encode(credentials).decode("ascii"),
            "Accept": "application/json",
            "User-Agent": "generated-backend-payments/1",
        }
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["X-Refund-Idempotency"] = idempotency_key
        safe_to_repeat = repeatable if repeatable is not None else (method == "GET")
        attempts = 1 + (_RETRIES if safe_to_repeat else 0)
        last = "network_error"
        for attempt in range(attempts):
            request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
            try:
                with _OPENER.open(  # noqa: S310 - scheme checked in settings
                    request, timeout=settings.payments_provider_timeout_seconds
                ) as response:
                    return self._parse(response.read(_MAX_RESPONSE_BYTES + 1))
            except urllib.error.HTTPError as exc:
                payload = exc.read(_MAX_RESPONSE_BYTES + 1)
                if exc.code == 429 or exc.code >= 500 or exc.code == 409:
                    last = f"http_{exc.code}"  # 409: an identical request is still in flight
                else:
                    raise ProviderRejected(self._error_code(payload, exc.code)) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                last = "network_error"
            if attempt + 1 < attempts:
                time.sleep(0.4 * (2**attempt))
        raise ProviderUnavailable(last)

    @staticmethod
    def _parse(data: bytes) -> dict[str, Any]:
        if len(data) > _MAX_RESPONSE_BYTES:
            raise ProviderUnavailable("response_too_large")
        try:
            parsed = json.loads(data)
        except ValueError:
            raise ProviderUnavailable("bad_response") from None
        if not isinstance(parsed, dict):
            raise ProviderUnavailable("bad_response")
        return parsed

    @staticmethod
    def _error_code(data: bytes, status: int) -> str:
        try:
            error = json.loads(data).get("error", {})
            for key in ("reason", "code"):
                value = error.get(key)
                if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_]{1,64}", value):
                    return value.lower()
        except (ValueError, AttributeError):
            pass
        return f"http_{status}"

    async def _acall(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._call, *args, **kwargs)

    # --- checkout (payment links) -------------------------------------------------------

    def _checkout(self, data: dict[str, Any]) -> ProviderCheckout:
        link_id = _safe_id(data.get("id"))
        amount = data.get("amount")
        currency = data.get("currency")
        if link_id is None or not isinstance(amount, int) or not isinstance(currency, str):
            raise ProviderUnavailable("bad_response")
        status = _LINK_STATUS.get(str(data.get("status")), "open")
        paid_amount = data.get("amount_paid")
        paid = status == "complete" and paid_amount == amount
        payment_id = None
        payments = data.get("payments")
        if isinstance(payments, list) and payments and isinstance(payments[0], dict):
            payment_id = _safe_id(payments[0].get("payment_id"))
        short_url = data.get("short_url")
        return ProviderCheckout(
            session_id=link_id,
            url=short_url if isinstance(short_url, str) else None,
            status=status,
            paid=paid,
            payment_pending=False,
            payment_intent_id=payment_id,
            amount_minor=amount,
            currency=currency.upper(),
            livemode=self._settings.livemode,
            payment_id=_uuid_or_none(data.get("reference_id")),
        )

    async def create_checkout(self, request: CheckoutRequest) -> ProviderCheckout:
        body = {
            "amount": request.amount_minor,
            "currency": request.currency.upper(),
            "accept_partial": False,
            "reference_id": request.payment_id,
            "description": request.description[:200],
            "expire_by": int(request.expires_at.timestamp()),
            "callback_url": request.success_url,
            "callback_method": "get",
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": {"payment_id": request.payment_id},
        }
        try:
            data = await self._acall("POST", "/v1/payment_links", body, repeatable=False)
        except ProviderUnavailable:
            # The answer may have been lost after the link was made: look it up by our reference
            # before anyone repeats the creation (a second one would be refused anyway).
            existing = await self._find_by_reference(request.payment_id)
            if existing is None:
                raise
            return self._checkout(existing)
        except ProviderRejected:
            existing = await self._find_by_reference(request.payment_id)
            if existing is not None:
                return self._checkout(existing)
            raise
        return self._checkout(data)

    async def _find_by_reference(self, reference: str) -> dict[str, Any] | None:
        try:
            data = await self._acall(
                "GET", "/v1/payment_links?" + urllib.parse.urlencode({"reference_id": reference})
            )
        except (ProviderUnavailable, ProviderRejected):
            return None
        links = data.get("payment_links")
        if isinstance(links, list):
            for link in links:
                if isinstance(link, dict) and link.get("reference_id") == reference:
                    return link
        return None

    async def retrieve_checkout(self, session_id: str) -> ProviderCheckout:
        self._require_id(session_id)
        return self._checkout(await self._acall("GET", f"/v1/payment_links/{session_id}"))

    async def expire_checkout(self, session_id: str) -> ProviderCheckout:
        self._require_id(session_id)
        data = await self._acall("POST", f"/v1/payment_links/{session_id}/cancel", {}, repeatable=True)
        return self._checkout(data)

    # --- refunds and disputes ---------------------------------------------------------

    @staticmethod
    def _refund(data: dict[str, Any]) -> ProviderRefund:
        refund_id = _safe_id(data.get("id"))
        amount = data.get("amount")
        status = _REFUND_STATUS.get(str(data.get("status")))
        if refund_id is None or not isinstance(amount, int) or status is None:
            raise ProviderUnavailable("bad_response")
        notes = data.get("notes") if isinstance(data.get("notes"), dict) else {}
        return ProviderRefund(
            refund_id=refund_id,
            status=status,
            amount_minor=amount,
            currency=str(data.get("currency", "")).upper(),
            payment_intent_id=_safe_id(data.get("payment_id")),
            our_refund_id=_uuid_or_none(notes.get("refund_id")) if isinstance(notes, dict) else None,
            failure_code="refund_failed" if status == "failed" else None,
        )

    async def create_refund(self, request: RefundRequest) -> ProviderRefund:
        self._require_id(request.payment_intent_id)
        body = {
            "amount": request.amount_minor,
            "speed": "normal",
            "receipt": request.refund_id,
            "notes": {"refund_id": request.refund_id, "reason": request.reason},
        }
        data = await self._acall(
            "POST",
            f"/v1/payments/{request.payment_intent_id}/refund",
            body,
            idempotency_key=request.idempotency_key,
            repeatable=True,
        )
        return self._refund(data)

    async def retrieve_refund(self, refund_id: str) -> ProviderRefund:
        self._require_id(refund_id)
        return self._refund(await self._acall("GET", f"/v1/refunds/{refund_id}"))

    async def list_refunds(self, payment_intent_id: str) -> list[ProviderRefund]:
        self._require_id(payment_intent_id)
        data = await self._acall("GET", f"/v1/payments/{payment_intent_id}/refunds?count=100")
        items = data.get("items")
        if not isinstance(items, list):
            raise ProviderUnavailable("bad_response")
        return [self._refund(item) for item in items if isinstance(item, dict)]

    async def retrieve_dispute(self, dispute_id: str) -> ProviderDispute:
        self._require_id(dispute_id)
        data = await self._acall("GET", f"/v1/disputes/{dispute_id}")
        dispute = _safe_id(data.get("id"))
        amount = data.get("amount")
        if dispute is None or not isinstance(amount, int):
            raise ProviderUnavailable("bad_response")
        reason = data.get("reason_code")
        return ProviderDispute(
            dispute_id=dispute,
            status=_DISPUTE_STATUS.get(str(data.get("status")), "open"),
            reason=reason[:64] if isinstance(reason, str) else None,
            amount_minor=amount,
            currency=str(data.get("currency", "")).upper(),
            payment_intent_id=_safe_id(data.get("payment_id")),
            evidence_due_by=_timestamp(data.get("respond_by")),
            created=_timestamp(data.get("created_at")),
        )

    @staticmethod
    def _require_id(value: str) -> None:
        if not _ID_RE.fullmatch(value):
            raise ProviderRejected("invalid_id")

    # --- webhooks ---------------------------------------------------------------------

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], now: float | None = None
    ) -> ProviderEvent:
        """Check the signature over the raw body, then parse. Nothing is parsed before it passes."""
        signature = headers.get("x-razorpay-signature") or headers.get("X-Razorpay-Signature") or ""
        event_id = headers.get("x-razorpay-event-id") or headers.get("X-Razorpay-Event-Id") or ""
        if not signature:
            raise WebhookRejected("missing_signature")
        if not _SIGNATURE_RE.fullmatch(signature):
            raise WebhookRejected("malformed_signature")
        valid = False
        for secret in self._settings.webhook_secrets():
            expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            valid |= hmac.compare_digest(expected, signature.lower())
        if not valid:
            raise WebhookRejected("bad_signature")
        if not _EVENT_ID_RE.fullmatch(event_id):
            raise WebhookRejected("missing_event_id")
        return self._parse_event(raw_body, event_id)

    def _parse_event(self, raw_body: bytes, event_id: str) -> ProviderEvent:
        try:
            event = json.loads(raw_body)
        except ValueError:
            raise WebhookRejected("malformed_body") from None
        if not isinstance(event, dict):
            raise WebhookRejected("malformed_body")
        event_type, payload = event.get("event"), event.get("payload")
        if (
            not isinstance(event_type, str)
            or not re.fullmatch(r"[a-z0-9_.]{1,100}", event_type)
            or not isinstance(payload, dict)
        ):
            raise WebhookRejected("malformed_event")
        refs, summary = _event_refs(event_type, payload)
        created = _timestamp(event.get("created_at"))
        kind, hint = _EVENT_KINDS.get(event_type, ("ignore", None))
        livemode = self._settings.livemode
        reduced: dict[str, object] = {
            "kind": kind,
            "hint": hint,
            "type": event_type,
            "id": event_id,
            "created": event.get("created_at") if isinstance(event.get("created_at"), int) else None,
            "livemode": livemode,
            "refs": refs,
            "summary": summary,
        }
        return ProviderEvent(event_id, event_type, livemode, created, refs, reduced)


def _entity(payload: dict[str, Any], name: str) -> dict[str, Any]:
    wrapper = payload.get(name)
    entity = wrapper.get("entity") if isinstance(wrapper, dict) else None
    return entity if isinstance(entity, dict) else {}


def _event_refs(event_type: str, payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, object]]:
    """The ids and amounts of an event, nothing personal."""
    refs: dict[str, str] = {}
    summary: dict[str, object] = {}
    if event_type.startswith("payment_link."):
        entity = _entity(payload, "payment_link")
        link = _safe_id(entity.get("id"))
        if link:
            refs["session"] = link
        ours = _uuid_or_none(entity.get("reference_id"))
        if ours:
            refs["payment_id"] = ours
        paid_payment = _safe_id(_entity(payload, "payment").get("id"))
        if paid_payment:
            refs["payment_intent"] = paid_payment
    elif event_type.startswith("refund."):
        entity = _entity(payload, "refund")
        refund = _safe_id(entity.get("id"))
        if refund:
            refs["refund"] = refund
        intent = _safe_id(entity.get("payment_id"))
        if intent:
            refs["payment_intent"] = intent
    elif event_type.startswith("payment.dispute."):
        entity = _entity(payload, "dispute")
        dispute = _safe_id(entity.get("id"))
        if dispute:
            refs["dispute"] = dispute
        intent = _safe_id(entity.get("payment_id"))
        if intent:
            refs["payment_intent"] = intent
    else:
        entity = {}
    for key in ("status", "amount", "amount_paid", "currency", "reason_code"):
        value = _scalar(entity.get(key))
        if value is not None:
            summary[key] = value
    return refs, summary
