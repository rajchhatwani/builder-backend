"""Stripe adapter (generated): Checkout Sessions, refunds, disputes and signed webhooks.

Only the standard library talks to Stripe (urllib, hmac). Card data never reaches this code: the
payer enters it on Stripe's hosted page. Every request has a timeout, TLS is verified, responses are
size-capped, retries happen only for calls that are safe to repeat (reads, or writes that carry an
idempotency key), and nothing the provider says in prose is passed on.
"""

import asyncio
import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
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

# Pinned, never "latest": an audit needs to know which API behaviour the code was written for.
# Re-check the field names used below against Stripe's changelog whenever this changes.
STRIPE_API_VERSION = "2024-06-20"
_MAX_RESPONSE_BYTES = 1_048_576
_RETRIES = 2
_ID_RE = re.compile(r"[A-Za-z0-9_]{3,255}")
_MAX_SIGNATURE_PARTS = 10

# Stripe event type -> (kind, hint). The kinds are the provider-neutral vocabulary events.py
# understands: checkout, refund, refunds_of_payment, dispute. Anything not listed is ignored.
_EVENT_KINDS: dict[str, tuple[str, str | None]] = {
    "checkout.session.completed": ("checkout", None),
    "checkout.session.async_payment_succeeded": ("checkout", None),
    "checkout.session.async_payment_failed": ("checkout", "failed"),
    "checkout.session.expired": ("checkout", None),
    "refund.created": ("refund", None),
    "refund.updated": ("refund", None),
    "refund.failed": ("refund", None),
    "charge.refund.updated": ("refund", None),
    "charge.refunded": ("refunds_of_payment", None),
    "charge.dispute.created": ("dispute", None),
    "charge.dispute.updated": ("dispute", None),
    "charge.dispute.closed": ("dispute", None),
    "charge.dispute.funds_withdrawn": ("dispute", None),
    "charge.dispute.funds_reinstated": ("dispute", None),
}

_DISPUTE_STATUS = {
    "needs_response": "open",
    "warning_needs_response": "open",
    "under_review": "under_review",
    "warning_under_review": "under_review",
    "won": "won",
    "lost": "lost",
    "warning_closed": "closed",
    "charge_refunded": "closed",
}
_REFUND_STATUS = {
    "pending": "pending",
    "requires_action": "pending",
    "succeeded": "succeeded",
    "failed": "failed",
    "canceled": "canceled",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A provider API never needs to redirect, and following a redirect could carry our credentials
    to another host (urllib keeps the Authorization header), so a redirect is simply an error."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _flatten(prefix: str, value: Any, out: list[tuple[str, str]]) -> None:
    """Stripe's form encoding: nested dicts and lists use bracket notation."""
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten(f"{prefix}[{key}]" if prefix else str(key), item, out)
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _flatten(f"{prefix}[{index}]", item, out)
    elif isinstance(value, bool):
        out.append((prefix, "true" if value else "false"))
    elif value is not None:
        out.append((prefix, str(value)))


def encode_form(params: Mapping[str, Any]) -> bytes:
    pairs: list[tuple[str, str]] = []
    _flatten("", dict(params), pairs)
    return urllib.parse.urlencode(pairs).encode("ascii")


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


class StripeProvider:
    name = "stripe"

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
        params: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        settings = self._settings
        url = settings.api_base.rstrip("/") + path
        body = encode_form(params) if params else None
        headers = {
            "Authorization": f"Bearer {settings.secret_key()}",
            "Stripe-Version": STRIPE_API_VERSION,
            "Accept": "application/json",
            "User-Agent": "generated-backend-payments/1",
        }
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        repeatable = method == "GET" or idempotency_key is not None
        attempts = 1 + (_RETRIES if repeatable else 0)
        last = "network_error"
        for attempt in range(attempts):
            request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
            try:
                with _OPENER.open(  # noqa: S310 - scheme checked in settings
                    request, timeout=settings.payments_provider_timeout_seconds
                ) as response:
                    return self._parse(response.read(_MAX_RESPONSE_BYTES + 1))
            except urllib.error.HTTPError as exc:
                data = exc.read(_MAX_RESPONSE_BYTES + 1)
                if exc.code == 429 or exc.code >= 500:
                    last = f"http_{exc.code}"
                else:
                    raise ProviderRejected(self._error_code(data, exc.code)) from None
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
            code = error.get("code") or error.get("type")
            if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,64}", code):
                return code
        except (ValueError, AttributeError):
            pass
        return f"http_{status}"

    async def _acall(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._call, *args, **kwargs)

    # --- checkout -------------------------------------------------------------------

    @staticmethod
    def _checkout(data: dict[str, Any]) -> ProviderCheckout:
        session_id = _safe_id(data.get("id"))
        amount = data.get("amount_total")
        currency = data.get("currency")
        if session_id is None or not isinstance(amount, int) or not isinstance(currency, str):
            raise ProviderUnavailable("bad_response")
        status = data.get("status")
        payment_status = data.get("payment_status")
        return ProviderCheckout(
            session_id=session_id,
            url=data.get("url") if isinstance(data.get("url"), str) else None,
            status=status if status in ("open", "complete", "expired") else "open",
            paid=status == "complete" and payment_status == "paid",
            payment_pending=status == "complete" and payment_status == "unpaid",
            payment_intent_id=_safe_id(data.get("payment_intent")),
            amount_minor=amount,
            currency=currency.upper(),
            livemode=data.get("livemode") is True,
            payment_id=_scalar(data.get("client_reference_id")) or None,  # type: ignore[arg-type]
        )

    async def create_checkout(self, request: CheckoutRequest) -> ProviderCheckout:
        params = {
            "mode": "payment",
            "success_url": request.success_url,
            "cancel_url": request.cancel_url,
            "client_reference_id": request.payment_id,
            "expires_at": int(request.expires_at.timestamp()),
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": request.currency.lower(),
                        "unit_amount": request.amount_minor,
                        "product_data": {"name": request.description},
                    },
                }
            ],
            "metadata": {"payment_id": request.payment_id},
            "payment_intent_data": {"metadata": {"payment_id": request.payment_id}},
        }
        data = await self._acall(
            "POST", "/v1/checkout/sessions", params, idempotency_key=request.idempotency_key
        )
        return self._checkout(data)

    async def retrieve_checkout(self, session_id: str) -> ProviderCheckout:
        self._require_id(session_id)
        return self._checkout(await self._acall("GET", f"/v1/checkout/sessions/{session_id}"))

    async def expire_checkout(self, session_id: str) -> ProviderCheckout:
        self._require_id(session_id)
        data = await self._acall(
            "POST", f"/v1/checkout/sessions/{session_id}/expire", {}, idempotency_key=None
        )
        return self._checkout(data)

    # --- refunds and disputes ---------------------------------------------------------

    @staticmethod
    def _refund(data: dict[str, Any]) -> ProviderRefund:
        refund_id = _safe_id(data.get("id"))
        amount = data.get("amount")
        status = _REFUND_STATUS.get(str(data.get("status")))
        if refund_id is None or not isinstance(amount, int) or status is None:
            raise ProviderUnavailable("bad_response")
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        failure = data.get("failure_reason")
        return ProviderRefund(
            refund_id=refund_id,
            status=status,
            amount_minor=amount,
            currency=str(data.get("currency", "")).upper(),
            payment_intent_id=_safe_id(data.get("payment_intent")),
            our_refund_id=_scalar(metadata.get("refund_id")) or None,  # type: ignore[arg-type]
            failure_code=failure[:64] if isinstance(failure, str) else None,
        )

    async def create_refund(self, request: RefundRequest) -> ProviderRefund:
        params = {
            "payment_intent": request.payment_intent_id,
            "amount": request.amount_minor,
            "reason": request.reason,
            "metadata": {"refund_id": request.refund_id},
        }
        data = await self._acall(
            "POST", "/v1/refunds", params, idempotency_key=request.idempotency_key
        )
        return self._refund(data)

    async def retrieve_refund(self, refund_id: str) -> ProviderRefund:
        self._require_id(refund_id)
        return self._refund(await self._acall("GET", f"/v1/refunds/{refund_id}"))

    async def list_refunds(self, payment_intent_id: str) -> list[ProviderRefund]:
        self._require_id(payment_intent_id)
        data = await self._acall(
            "GET", f"/v1/refunds?payment_intent={payment_intent_id}&limit=100"
        )
        items = data.get("data")
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
        details = data.get("evidence_details")
        due = details.get("due_by") if isinstance(details, dict) else None
        reason = data.get("reason")
        return ProviderDispute(
            dispute_id=dispute,
            status=_DISPUTE_STATUS.get(str(data.get("status")), "open"),
            reason=reason[:64] if isinstance(reason, str) else None,
            amount_minor=amount,
            currency=str(data.get("currency", "")).upper(),
            payment_intent_id=_safe_id(data.get("payment_intent")),
            evidence_due_by=_timestamp(due),
            created=_timestamp(data.get("created")),
        )

    @staticmethod
    def _require_id(value: str) -> None:
        if not _ID_RE.fullmatch(value):
            raise ProviderRejected("invalid_id")

    # --- webhooks ---------------------------------------------------------------------

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], now: float | None = None
    ) -> ProviderEvent:
        """Check the signature and age, then parse. Nothing is parsed before the check passes."""
        settings = self._settings
        header = headers.get("stripe-signature") or headers.get("Stripe-Signature")
        if not header:
            raise WebhookRejected("missing_signature")
        timestamp, signatures = self._parse_signature_header(header)
        current = time.time() if now is None else now
        if abs(current - timestamp) > config.WEBHOOK_TOLERANCE_SECONDS:
            raise WebhookRejected("timestamp_out_of_tolerance")
        signed = f"{timestamp}.".encode("ascii") + raw_body
        valid = False
        for secret in settings.webhook_secrets():
            expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
            for candidate in signatures:
                # Compare every pair so timing does not reveal which secret or signature matched.
                valid |= hmac.compare_digest(expected, candidate)
        if not valid:
            raise WebhookRejected("bad_signature")
        return self._parse_event(raw_body, settings.livemode)

    @staticmethod
    def _parse_signature_header(header: str) -> tuple[int, list[str]]:
        parts = header.split(",")
        if len(parts) > _MAX_SIGNATURE_PARTS:
            raise WebhookRejected("malformed_signature")
        timestamp: int | None = None
        signatures: list[str] = []
        for part in parts:
            key, _, value = part.strip().partition("=")
            if key == "t" and value.isdigit() and len(value) <= 12:
                timestamp = int(value)
            elif key == "v1" and re.fullmatch(r"[0-9a-fA-F]{64}", value):
                signatures.append(value.lower())
        if timestamp is None or not signatures:
            raise WebhookRejected("malformed_signature")
        return timestamp, signatures

    @staticmethod
    def _parse_event(raw_body: bytes, expected_livemode: bool) -> ProviderEvent:
        try:
            event = json.loads(raw_body)
        except ValueError:
            raise WebhookRejected("malformed_body") from None
        if not isinstance(event, dict):
            raise WebhookRejected("malformed_body")
        event_id, event_type = _safe_id(event.get("id")), event.get("type")
        data = event.get("data")
        obj = data.get("object") if isinstance(data, dict) else None
        if (
            event_id is None
            or not isinstance(event_type, str)
            or not re.fullmatch(r"[a-z0-9_.]{1,100}", event_type)
            or not isinstance(event.get("livemode"), bool)
            or not isinstance(obj, dict)
        ):
            raise WebhookRejected("malformed_event")
        if event["livemode"] != expected_livemode:
            raise WebhookRejected("livemode_mismatch")
        refs, summary = _event_refs(obj)
        created = _timestamp(event.get("created"))
        kind, hint = _EVENT_KINDS.get(event_type, ("ignore", None))
        reduced: dict[str, object] = {
            "kind": kind,
            "hint": hint,
            "type": event_type,
            "id": event_id,
            "created": event.get("created") if isinstance(event.get("created"), int) else None,
            "livemode": event["livemode"],
            "api_version": _scalar(event.get("api_version")),
            "object": _scalar(obj.get("object")),
            "refs": refs,
            "summary": summary,
        }
        return ProviderEvent(event_id, event_type, event["livemode"], created, refs, reduced)


def _event_refs(obj: dict[str, Any]) -> tuple[dict[str, str], dict[str, object]]:
    """The ids and amounts of an event object, nothing personal."""
    kind = obj.get("object")
    own = _safe_id(obj.get("id"))
    refs: dict[str, str] = {}
    pairs: list[tuple[str, str | None]] = [("payment_intent", _safe_id(obj.get("payment_intent")))]
    if kind == "checkout.session":
        pairs.append(("session", own))
    elif kind == "payment_intent":
        pairs.append(("payment_intent", own))
    elif kind == "charge":
        pairs.append(("charge", own))
    elif kind == "refund":
        pairs.append(("refund", own))
        pairs.append(("charge", _safe_id(obj.get("charge"))))
    elif kind == "dispute":
        pairs.append(("dispute", own))
        pairs.append(("charge", _safe_id(obj.get("charge"))))
    for name, value in pairs:
        if value is not None:
            refs[name] = value
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    ours = _scalar(metadata.get("payment_id")) or _scalar(obj.get("client_reference_id"))
    if isinstance(ours, str) and re.fullmatch(r"[0-9a-f-]{36}", ours):
        refs["payment_id"] = ours
    summary: dict[str, object] = {}
    for key in ("status", "payment_status", "amount", "amount_total", "amount_refunded", "currency", "reason"):
        value = _scalar(obj.get(key))
        if value is not None:
            summary[key] = value
    return refs, summary
