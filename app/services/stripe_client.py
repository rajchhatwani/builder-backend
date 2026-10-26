"""The few Stripe API calls the platform makes, over plain HTTPS with `httpx`.

No Stripe SDK dependency. Card data never reaches the Builder: Checkout and the Billing
Portal are hosted by Stripe. Error text from Stripe is not returned to callers verbatim;
`StripeError` carries it for server logs only.

Calls:
  - `create_checkout_session` — Phase B, first purchase for an org.
  - `create_portal_session`   — Phase C, plan change / card / cancel for a paying org.
  - `get_subscription`, `set_item_quantity` — Phase C.4 seat sync.
  - `verify_webhook`          — Phase C.3, pure: checks `Stripe-Signature`, then parses.
"""

import hashlib
import hmac
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import httpx

STRIPE_API = "https://api.stripe.com/v1"
TIMEOUT_SECONDS = 15.0
DEFAULT_WEBHOOK_TOLERANCE = 300
_MAX_SIGNATURE_PARTS = 16
_V1_RE = re.compile(r"[0-9a-fA-F]{64}")


class StripeError(Exception):
    """Stripe refused the request or could not be reached."""


class WebhookSignatureError(Exception):
    """A webhook delivery failed verification. `reason` is safe to log; never show callers."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


@dataclass(frozen=True)
class SubscriptionInfo:
    """The parts of a Stripe Subscription seat sync needs: its single seat line item."""

    id: str
    item_id: str
    quantity: int


async def _call(
    method: Literal["GET", "POST"],
    path: str,
    *,
    secret_key: str,
    form: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {secret_key}"}
    if method == "POST":
        # Safe for retries on our side; Stripe dedupes a repeated key for 24 h.
        headers["Idempotency-Key"] = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_SECONDS) as client:
            if method == "GET":
                response = await client.get(f"{STRIPE_API}{path}", headers=headers)
            else:
                response = await client.post(f"{STRIPE_API}{path}", data=form, headers=headers)
    except httpx.HTTPError as exc:
        raise StripeError(f"stripe unreachable: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        try:
            message = response.json().get("error", {}).get("message", "")
        except ValueError:
            message = ""
        raise StripeError(f"stripe {response.status_code}: {message}")
    try:
        return response.json()
    except ValueError as exc:
        raise StripeError("stripe returned a non-JSON body") from exc


async def create_checkout_session(
    *,
    secret_key: str,
    price_id: str,
    quantity: int,
    organization_id: uuid.UUID,
    plan_id: str,
    customer_id: str | None,
    customer_email: str | None,
    success_url: str,
    cancel_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CheckoutSession:
    """Create a subscription-mode Checkout Session for one org upgrading to one plan.

    The org id rides in `client_reference_id` and in metadata on both the session and the
    subscription, so the Phase C webhook can map events back to the org.
    """
    org = str(organization_id)
    form: dict[str, str] = {
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": str(max(quantity, 1)),
        "client_reference_id": org,
        "metadata[organization_id]": org,
        "metadata[plan_id]": plan_id,
        "subscription_data[metadata][organization_id]": org,
        "subscription_data[metadata][plan_id]": plan_id,
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    if customer_id:
        form["customer"] = customer_id
    elif customer_email:
        form["customer_email"] = customer_email
    body = await _call(
        "POST", "/checkout/sessions", secret_key=secret_key, form=form, transport=transport
    )
    return CheckoutSession(id=body["id"], url=body["url"])


async def create_portal_session(
    *,
    secret_key: str,
    customer_id: str,
    return_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """A Billing Portal session for the org's one Customer; returns the hosted URL."""
    body = await _call(
        "POST",
        "/billing_portal/sessions",
        secret_key=secret_key,
        form={"customer": customer_id, "return_url": return_url},
        transport=transport,
    )
    return str(body["url"])


async def get_subscription(
    *,
    secret_key: str,
    subscription_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SubscriptionInfo:
    body = await _call(
        "GET", f"/subscriptions/{subscription_id}", secret_key=secret_key, transport=transport
    )
    items = (body.get("items") or {}).get("data") or []
    if not items:
        raise StripeError("stripe subscription has no line items")
    # Checkout creates the subscription with one line item: the plan's per-seat Price.
    item = items[0]
    return SubscriptionInfo(
        id=str(body["id"]), item_id=str(item["id"]), quantity=int(item.get("quantity") or 0)
    )


async def set_item_quantity(
    *,
    secret_key: str,
    item_id: str,
    quantity: int,
    proration_behavior: Literal["create_prorations", "none", "always_invoice"],
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    await _call(
        "POST",
        f"/subscription_items/{item_id}",
        secret_key=secret_key,
        form={"quantity": str(max(quantity, 1)), "proration_behavior": proration_behavior},
        transport=transport,
    )


# -- webhook verification -----------------------------------------------------------------


def _parse_signature_header(header: str) -> tuple[int, list[str]]:
    parts = header.split(",")
    if len(parts) > _MAX_SIGNATURE_PARTS:
        raise WebhookSignatureError("malformed_signature")
    timestamp: int | None = None
    signatures: list[str] = []
    for part in parts:
        key, _, value = part.strip().partition("=")
        if key == "t" and value.isdigit() and len(value) <= 12:
            timestamp = int(value)
        elif key == "v1" and _V1_RE.fullmatch(value):
            signatures.append(value.lower())
    if timestamp is None or not signatures:
        raise WebhookSignatureError("malformed_signature")
    return timestamp, signatures


def verify_webhook(
    payload: bytes,
    header: str | None,
    secrets: list[str],
    *,
    now: float | None = None,
    tolerance: int = DEFAULT_WEBHOOK_TOLERANCE,
) -> dict[str, Any]:
    """Check `Stripe-Signature` against every configured secret, then parse the event.

    Nothing is parsed before the signature passes. Every (secret, signature) pair is
    compared so timing does not reveal which one matched.
    """
    if not secrets:
        raise WebhookSignatureError("not_configured")
    if not header:
        raise WebhookSignatureError("missing_signature")
    timestamp, signatures = _parse_signature_header(header)
    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance:
        raise WebhookSignatureError("timestamp_out_of_tolerance")
    signed = f"{timestamp}.".encode("ascii") + payload
    valid = False
    for secret in secrets:
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        for candidate in signatures:
            valid |= hmac.compare_digest(expected, candidate)
    if not valid:
        raise WebhookSignatureError("bad_signature")
    try:
        event = json.loads(payload)
    except ValueError:
        raise WebhookSignatureError("malformed_body") from None
    if not isinstance(event, dict) or not isinstance(event.get("id"), str):
        raise WebhookSignatureError("malformed_body")
    return event
