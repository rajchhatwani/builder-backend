"""What the payments service needs from a payment provider (generated).

Each provider (Stripe, Razorpay) implements `PaymentProvider` and translates its own vocabulary
into these small types, so the service, the state machine and the tests never depend on a
provider's field names. Provider text (error messages, customer details) is never carried across
this boundary: only codes, ids, statuses and amounts.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class ProviderError(Exception):
    """Base class for provider failures. `code` is ours or the provider's short code, never text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProviderUnavailable(ProviderError):
    """Network trouble, a timeout, a 5xx or rate limiting: the same call may be retried."""


class ProviderRejected(ProviderError):
    """The provider refused the request itself: retrying the same request will not help."""


class WebhookRejected(Exception):
    """A webhook failed verification. `reason` goes to the log, never to the caller."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CheckoutRequest:
    payment_id: str
    amount_minor: int
    currency: str
    description: str
    success_url: str
    cancel_url: str
    expires_at: datetime
    idempotency_key: str


@dataclass(frozen=True)
class ProviderCheckout:
    session_id: str
    url: str | None
    status: str  # open | complete | expired
    paid: bool  # the money is confirmed
    payment_pending: bool  # complete, but a slow payment method has not confirmed yet
    payment_intent_id: str | None
    amount_minor: int
    currency: str
    livemode: bool
    payment_id: str | None  # our payment id echoed back by the provider


@dataclass(frozen=True)
class RefundRequest:
    refund_id: str
    payment_intent_id: str
    amount_minor: int
    reason: str
    idempotency_key: str


@dataclass(frozen=True)
class ProviderRefund:
    refund_id: str
    status: str  # pending | succeeded | failed | canceled
    amount_minor: int
    currency: str
    payment_intent_id: str | None
    our_refund_id: str | None  # our refund id echoed back, if we created it
    failure_code: str | None = None


@dataclass(frozen=True)
class ProviderDispute:
    dispute_id: str
    status: str  # open | under_review | won | lost | closed
    reason: str | None
    amount_minor: int
    currency: str
    payment_intent_id: str | None
    evidence_due_by: datetime | None
    created: datetime | None


@dataclass(frozen=True)
class ProviderEvent:
    event_id: str
    type: str
    livemode: bool
    created: datetime | None
    refs: dict[str, str] = field(default_factory=dict)  # session, payment_intent, charge, ...
    reduced: dict[str, object] = field(default_factory=dict)  # what we store of the payload


class PaymentProvider(Protocol):
    name: str

    async def create_checkout(self, request: CheckoutRequest) -> ProviderCheckout: ...

    async def retrieve_checkout(self, session_id: str) -> ProviderCheckout: ...

    async def expire_checkout(self, session_id: str) -> ProviderCheckout: ...

    async def create_refund(self, request: RefundRequest) -> ProviderRefund: ...

    async def retrieve_refund(self, refund_id: str) -> ProviderRefund: ...

    async def list_refunds(self, payment_intent_id: str) -> list[ProviderRefund]: ...

    async def retrieve_dispute(self, dispute_id: str) -> ProviderDispute: ...

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], now: float | None = None
    ) -> ProviderEvent: ...
