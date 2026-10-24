"""Validation rules for the `payments` block of a spec.

Kept apart from validation.py (which imports this module) and therefore free of its types: issues
are reported through the `add(path, code, message)` callable it passes in.
"""

import re
from collections.abc import Callable
from typing import Any

from app.core import currencies
from app.core.enums import (
    PaymentProvider,
    PaymentsAvailability,
    PaymentsProfile,
    WebhookMode,
)
from app.core.payments_sizing import size
from app.core.spec_models import Spec, SpecEntity, SpecPayments

Add = Callable[[str, str, str], None]
UrlProblem = Callable[[str], str | None]

# Tables the generated payments module creates; entities may not use these names.
PAYMENTS_TABLES = (
    "pay_audit_log",
    "pay_idempotency_keys",
    "pay_jobs",
    "pay_lock",
    "pay_payments",
    "pay_refunds",
    "pay_disputes",
    "pay_webhook_events",
)

_CURRENCY_RE = re.compile(r"[A-Z]{3}")
_MAX_URLS = 20

# Floors and ceilings for the security knobs: an unsafe value is rejected, never clamped.
TOLERANCE_SECONDS = (30, 600)
BODY_BYTES = (1024, 1_048_576)
IDEMPOTENCY_HOURS = (24, 168)
AUDIT_RETENTION_DAYS = (365, 36_500)
EVENTS_RETENTION_DAYS = (7, 3650)
JOBS_RETENTION_DAYS = (1, 365)

_OVERRIDE_RANGES = {
    "api_replicas": (1, 1000),
    "server_workers": (1, 64),
    "worker_replicas": (1, 1000),
    "worker_concurrency": (1, 256),
    "pool_size": (1, 100),
}
_ROLE_FIELDS = ("create", "read", "read_all", "refund", "approve_refund", "operate")


def payments_active(spec: Spec) -> bool:
    return spec.payments is not None and spec.payments.enabled


def check_payments(
    spec: Spec, entities: dict[str, SpecEntity], add: Add, url_problem: UrlProblem
) -> None:
    pay = spec.payments
    if pay is None:
        return
    _check_enums(pay, add)
    _check_security(pay, add)
    _check_scale(pay, add)
    if not pay.enabled:
        return  # work in progress: the rest is only enforced once payments are switched on

    auth = spec.auth
    if auth is None or not auth.enabled:
        add("payments", "requires_auth", "payments need authentication: turn auth on first")
    for i, entity in enumerate(spec.entities):
        if entity.plural_path == "payments":
            add(
                f"entities[{i}].plural_path",
                "reserved_word",
                "'payments' is the route of the payments module",
            )
    _check_money(pay, add)
    _check_urls(pay, add, url_problem)
    _check_roles(pay, spec, add)
    _check_payable(pay, spec, entities, add)
    _check_sizing(pay, add)


def _check_enums(pay: SpecPayments, add: Add) -> None:
    checks: list[tuple[str, str | None, type[Any]]] = [
        ("payments.provider", pay.provider, PaymentProvider),
        ("payments.scale.profile", pay.scale.profile, PaymentsProfile),
        ("payments.scale.availability", pay.scale.availability, PaymentsAvailability),
        ("payments.scale.webhook_mode", pay.scale.webhook_mode, WebhookMode),
    ]
    for path, value, enum in checks:
        if value is None:
            continue
        allowed = [e.value for e in enum]
        if value not in allowed:
            add(path, "invalid_value", f"must be one of {', '.join(allowed)}")


def _in(value: int, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= value <= bounds[1]


def _check_security(pay: SpecPayments, add: Add) -> None:
    sec = pay.security
    rules: list[tuple[str, int, tuple[int, int]]] = [
        ("webhook_tolerance_seconds", sec.webhook_tolerance_seconds, TOLERANCE_SECONDS),
        ("webhook_max_body_bytes", sec.webhook_max_body_bytes, BODY_BYTES),
        ("idempotency_ttl_hours", sec.idempotency_ttl_hours, IDEMPOTENCY_HOURS),
        ("audit_retention_days", sec.audit_retention_days, AUDIT_RETENTION_DAYS),
    ]
    for name, value, bounds in rules:
        if not _in(value, bounds):
            add(
                f"payments.security.{name}",
                "out_of_range",
                f"must be between {bounds[0]} and {bounds[1]}",
            )


def _check_scale(pay: SpecPayments, add: Add) -> None:
    scale = pay.scale
    for name, bounds in _OVERRIDE_RANGES.items():
        value = getattr(scale, name)
        if value is not None and not _in(value, bounds):
            add(
                f"payments.scale.{name}",
                "out_of_range",
                f"must be between {bounds[0]} and {bounds[1]}",
            )
    for name in ("peak_payments_per_minute", "peak_webhooks_per_minute"):
        value = getattr(scale, name)
        if value is not None and not 1 <= value <= 100_000_000:
            add(f"payments.scale.{name}", "out_of_range", "must be between 1 and 100000000")
    if not 10 <= scale.db_max_connections <= 100_000:
        add("payments.scale.db_max_connections", "out_of_range", "must be between 10 and 100000")
    if not _in(scale.webhook_events_retention_days, EVENTS_RETENTION_DAYS):
        add(
            "payments.scale.webhook_events_retention_days",
            "out_of_range",
            f"must be between {EVENTS_RETENTION_DAYS[0]} and {EVENTS_RETENTION_DAYS[1]}",
        )
    if not _in(scale.jobs_retention_days, JOBS_RETENTION_DAYS):
        add(
            "payments.scale.jobs_retention_days",
            "out_of_range",
            f"must be between {JOBS_RETENTION_DAYS[0]} and {JOBS_RETENTION_DAYS[1]}",
        )


def _check_sizing(pay: SpecPayments, add: Add) -> None:
    """The plan must fit the database, or say it needs a pooler."""
    try:
        sizing = size(pay.scale)
    except (ValueError, TypeError):  # bad numbers were reported above
        return
    if sizing.needs_pgbouncer:
        add(
            "payments.scale",
            "connection_budget",
            f"this load needs {sizing.total_db_connections} database connections but only "
            f"{sizing.connection_budget} fit in db_max_connections={pay.scale.db_max_connections}: "
            "turn on pgbouncer, raise db_max_connections or lower the replicas",
        )


def _check_money(pay: SpecPayments, add: Add) -> None:
    allowed = currencies.supported(pay.provider)
    if not pay.currencies:
        add("payments.currencies", "required", "list at least one currency")
    if len(pay.currencies) > 30:
        add("payments.currencies", "too_many", "at most 30 currencies")
    seen: set[str] = set()
    for i, code in enumerate(pay.currencies):
        path = f"payments.currencies[{i}]"
        if not _CURRENCY_RE.fullmatch(code):
            add(path, "invalid_value", "must be a 3-letter upper-case ISO 4217 code")
        elif code not in allowed:
            add(path, "unsupported", f"{code} is not supported for {pay.provider}")
        elif code in seen:
            add(path, "duplicate_name", f"{code} is listed twice")
        seen.add(code)
    cap = currencies.PROVIDER_MAX_AMOUNT_MINOR.get(pay.provider)
    if pay.max_amount_minor < 1 or (cap is not None and pay.max_amount_minor > cap):
        add(
            "payments.max_amount_minor",
            "out_of_range",
            f"must be between 1 and {cap} (the provider's limit)",
        )
    threshold = pay.refund_approval_threshold_minor
    if threshold is not None and not 1 <= threshold <= pay.max_amount_minor:
        add(
            "payments.refund_approval_threshold_minor",
            "out_of_range",
            "must be between 1 and max_amount_minor",
        )


def _check_urls(pay: SpecPayments, add: Add, url_problem: UrlProblem) -> None:
    for name, urls in (("success_urls", pay.success_urls), ("cancel_urls", pay.cancel_urls)):
        path = f"payments.{name}"
        if not urls:
            add(path, "required", "list at least one exact URL (checkout can only return there)")
        if len(urls) > _MAX_URLS:
            add(path, "too_many", f"at most {_MAX_URLS} URLs")
        if len(set(urls)) != len(urls):
            add(path, "duplicate_name", "each URL may be listed once")
        for i, url in enumerate(urls):
            problem = url_problem(url)
            if problem:
                add(f"{path}[{i}]", "invalid_value", f"URL {problem}")


def _check_roles(pay: SpecPayments, spec: Spec, add: Add) -> None:
    role_names = {r.name for r in spec.auth.roles} if spec.auth is not None else set()
    for name in _ROLE_FIELDS:
        roles: list[str] = getattr(pay.roles, name)
        path = f"payments.roles.{name}"
        if len(set(roles)) != len(roles):
            add(path, "duplicate_name", "each role may be listed once")
        for role in roles:
            if role not in role_names:
                add(path, "unknown_reference", f"role {role[:40]!r} does not exist")
    for name in ("create", "read"):
        if not getattr(pay.roles, name):
            add(
                f"payments.roles.{name}",
                "required",
                "list at least one role (an empty list means nobody may do it)",
            )
    if pay.refund_approval_threshold_minor is not None:
        if not pay.roles.refund:
            add("payments.roles.refund", "required", "needed when a refund threshold is set")
        if not pay.roles.approve_refund:
            add(
                "payments.roles.approve_refund",
                "required",
                "a second person must be able to approve refunds above the threshold",
            )


def _check_payable(
    pay: SpecPayments, spec: Spec, entities: dict[str, SpecEntity], add: Add
) -> None:
    payable = pay.payable
    if payable is None:
        add("payments.payable", "required", "say which entity a payment is for")
        return
    entity = entities.get(payable.entity)
    if entity is None:
        add("payments.payable.entity", "unknown_entity", f"no entity named {payable.entity[:40]!r}")
        return
    fields = {f.name: f for f in entity.fields}

    amount = fields.get(payable.amount_field)
    if amount is None:
        add("payments.payable.amount_field", "unknown_field", "no such field on the entity")
    elif amount.type != "decimal" or not amount.required:
        add("payments.payable.amount_field", "invalid_value", "must be a required decimal field")
    elif amount.min_value is None or amount.min_value <= 0:
        add(
            "payments.payable.amount_field",
            "invalid_value",
            "needs min_value above 0 so a zero or negative amount can never be charged",
        )

    if (
        pay.provider == "razorpay"
        and amount is not None
        and (amount.min_value is None or amount.min_value < 1)
    ):
        add(
            "payments.payable.amount_field",
            "invalid_value",
            "Razorpay refuses payments below 100 minor units (1.00): set min_value to at least 1",
        )

    _check_payable_currency(pay, fields, add)

    status = fields.get(payable.status_field)
    values = [
        payable.status_pending,
        payable.status_paid,
        payable.status_partially_refunded,
        payable.status_refunded,
    ]
    if status is None:
        add("payments.payable.status_field", "unknown_field", "no such field on the entity")
    elif status.type != "enum" or not status.required:
        add("payments.payable.status_field", "invalid_value", "must be a required enum field")
    else:
        for name, value in zip(
            ("pending", "paid", "partially_refunded", "refunded"), values, strict=True
        ):
            if value not in (status.enum_values or []):
                add(
                    f"payments.payable.status_{name}",
                    "invalid_value",
                    f"{value[:40]!r} is not one of the enum values of {payable.status_field}",
                )
    if len(set(values)) != len(values):
        add("payments.payable", "invalid_value", "the four status values must be different")

    _check_payable_access(pay, spec, entity, add)


def _check_payable_currency(pay: SpecPayments, fields: dict[str, Any], add: Add) -> None:
    payable = pay.payable
    assert payable is not None
    if (payable.currency is None) == (payable.currency_field is None):
        add("payments.payable", "invalid_value", "set exactly one of currency or currency_field")
    if payable.currency is not None and payable.currency not in pay.currencies:
        add("payments.payable.currency", "invalid_value", "must be one of payments.currencies")
    if payable.currency_field is not None:
        column = fields.get(payable.currency_field)
        if column is None:
            add("payments.payable.currency_field", "unknown_field", "no such field on the entity")
        elif column.type != "string" or not column.required or column.max_length != 3:
            add(
                "payments.payable.currency_field",
                "invalid_value",
                "must be a required string field with max_length 3",
            )


def _check_payable_access(pay: SpecPayments, spec: Spec, entity: SpecEntity, add: Add) -> None:
    """A payment trusts the amount on the payable row, so whoever can edit that row decides what
    gets charged. The row must never be reachable by anonymous callers, and in a multi-tenant
    project it must be confined to its tenant."""
    if spec.auth is None:
        return
    ops = set(entity.options.operations)
    by_op = {p.operation: p for p in spec.auth.permissions if p.entity == entity.name}
    for op in sorted(ops):
        perm = by_op.get(op)
        if perm is None or not perm.roles:
            add(
                "payments.payable.entity",
                "public_operation",
                f"{entity.name}.{op} has no role restriction: anyone could read or change what "
                "is charged. Give every operation of the payable entity at least one role",
            )
    if not pay.security.allow_payer_edits:
        _check_payers_cannot_write(pay, spec, entity, ops, by_op, add)
    if "get" not in ops:
        add(
            "payments.payable.entity",
            "invalid_value",
            "the payable entity needs the get operation (a payer must be allowed to read the row)",
        )
    if spec.auth.multi_tenant and not any(p.row_rule == "tenant" for p in by_op.values()):
        add(
            "payments.payable.entity",
            "not_tenant_scoped",
            "in a multi-tenant project the payable entity needs the tenant row rule",
        )


def _held(role: str, parents: dict[str, str | None]) -> set[str]:
    """A role and every role it inherits from."""
    held: set[str] = set()
    cursor: str | None = role
    while cursor is not None and cursor not in held:
        held.add(cursor)
        cursor = parents.get(cursor)
    return held


def _check_payers_cannot_write(
    pay: SpecPayments, spec: Spec, entity: SpecEntity, ops: set[str], by_op: dict[str, Any], add: Add
) -> None:
    """The amount charged is the amount on the payable row. If the people who pay may create or
    change that row, they set their own price. The platform has no read-only fields, so the only
    safe setup is that payers can read the row but not write it (it is created by staff or by
    your own server code). Every account also holds the default roles, so those count as payers."""
    assert spec.auth is not None
    parents = {r.name: r.inherits_from for r in spec.auth.roles}
    payers: set[str] = set()
    for role in [*pay.roles.create, *(r.name for r in spec.auth.roles if r.is_default)]:
        payers |= _held(role, parents)
    for op in ("create", "replace", "update", "delete"):
        perm = by_op.get(op)
        if op in ops and perm is not None and set(perm.roles) & payers:
            shared = ", ".join(sorted(set(perm.roles) & payers))
            add(
                "payments.payable.entity",
                "payer_can_set_amount",
                f"{entity.name}.{op} is open to {shared}, who can also pay: they could set their "
                "own price. Let only staff roles write the item (payers may read it), or accept "
                "the risk with payments.security.allow_payer_edits",
            )
