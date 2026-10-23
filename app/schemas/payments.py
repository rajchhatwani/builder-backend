"""Pydantic schemas for a project's payments settings (builder API layer).

Shapes and ranges are checked here; whether a combination is *legal* (the payable entity and its
fields, role names, URL rules, connection budgets) is `validation.validate`'s job, so the dashboard
can save work in progress and see every problem in one report. No field here can hold a provider
secret: API keys and webhook secrets are environment variables of the generated project.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import PaymentProvider, PaymentsAvailability, PaymentsProfile, WebhookMode


class Payable(BaseModel):
    entity: str = Field(min_length=1, max_length=100)
    amount_field: str = Field(min_length=1, max_length=100)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    currency_field: str | None = Field(default=None, min_length=1, max_length=100)
    status_field: str = Field(min_length=1, max_length=100)
    status_pending: str = Field(min_length=1, max_length=100)
    status_paid: str = Field(min_length=1, max_length=100)
    status_partially_refunded: str = Field(min_length=1, max_length=100)
    status_refunded: str = Field(min_length=1, max_length=100)


class PaymentsRoles(BaseModel):
    create: list[str] = Field(default_factory=list, max_length=50)
    read: list[str] = Field(default_factory=list, max_length=50)
    read_all: list[str] = Field(default_factory=list, max_length=50)
    refund: list[str] = Field(default_factory=list, max_length=50)
    approve_refund: list[str] = Field(default_factory=list, max_length=50)
    operate: list[str] = Field(default_factory=list, max_length=50)


class PaymentsScale(BaseModel):
    profile: PaymentsProfile = PaymentsProfile.small
    peak_payments_per_minute: int | None = Field(default=None, ge=1, le=10_000_000)
    peak_webhooks_per_minute: int | None = Field(default=None, ge=1, le=100_000_000)
    db_max_connections: int = Field(default=100, ge=10, le=100_000)
    availability: PaymentsAvailability = PaymentsAvailability.single
    pgbouncer: bool = False
    kubernetes: bool = False
    webhook_mode: WebhookMode | None = None
    api_replicas: int | None = Field(default=None, ge=1, le=1000)
    server_workers: int | None = Field(default=None, ge=1, le=64)
    worker_replicas: int | None = Field(default=None, ge=1, le=1000)
    worker_concurrency: int | None = Field(default=None, ge=1, le=256)
    pool_size: int | None = Field(default=None, ge=1, le=100)
    webhook_events_retention_days: int = Field(default=90, ge=1, le=100_000)
    jobs_retention_days: int = Field(default=30, ge=1, le=100_000)


class PaymentsSecurity(BaseModel):
    webhook_tolerance_seconds: int = Field(default=300, ge=1, le=1_000_000)
    webhook_max_body_bytes: int = Field(default=262_144, ge=1, le=100_000_000)
    webhook_ip_allowlist_enabled: bool = False
    idempotency_ttl_hours: int = Field(default=48, ge=1, le=100_000)
    audit_retention_days: int = Field(default=2555, ge=1, le=1_000_000)
    secrets_from_files: bool = True
    allow_payer_edits: bool = False


class PaymentsConfigWrite(BaseModel):
    """Body of PUT /projects/{id}/payments."""

    provider: PaymentProvider = PaymentProvider.stripe
    payable: Payable | None = None
    currencies: list[str] = Field(default_factory=list, max_length=30)
    max_amount_minor: int = Field(default=10_000_000, ge=1, le=9_000_000_000_000_000)
    success_urls: list[str] = Field(default_factory=list, max_length=20)
    cancel_urls: list[str] = Field(default_factory=list, max_length=20)
    roles: PaymentsRoles = Field(default_factory=PaymentsRoles)
    refund_approval_threshold_minor: int | None = Field(
        default=None, ge=1, le=9_000_000_000_000_000
    )
    scale: PaymentsScale = Field(default_factory=PaymentsScale)
    security: PaymentsSecurity = Field(default_factory=PaymentsSecurity)


class PaymentsConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    enabled: bool
    provider: PaymentProvider
    payable: Payable | None
    currencies: list[str]
    max_amount_minor: int
    success_urls: list[str]
    cancel_urls: list[str]
    roles: PaymentsRoles
    refund_approval_threshold_minor: int | None
    scale: PaymentsScale
    security: PaymentsSecurity
    created_at: datetime
    updated_at: datetime


class PaymentsSwitchRequest(BaseModel):
    """Body of POST .../payments/enable and .../payments/disable: both change what the next
    generated project contains, so the caller must say so."""

    confirm: bool = False


class PaymentsImpact(BaseModel):
    action: str  # "enable" | "disable"
    enabled: bool  # the current state
    can_proceed: bool
    blockers: list[str]
    warnings: list[str]


class PaymentsSizingRead(BaseModel):
    """Derived deployment shape for the saved scale settings (no side effects)."""

    sizing: dict[str, Any]
    issues: list[dict[str, Any]]
