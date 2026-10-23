"""Validation rules for the `payments` block of a spec. Pure Python."""

import copy
from collections.abc import Callable
from typing import Any

import pytest

from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, validate

OPS = ["list", "get", "create", "replace", "update", "delete", "head"]
READ_OPS = ("list", "get", "head")


def base_spec(**payments_overrides: Any) -> dict[str, Any]:
    payments: dict[str, Any] = {
        "enabled": True,
        "provider": "stripe",
        "payable": {
            "entity": "Order",
            "amount_field": "total",
            "currency_field": "currency",
            "status_field": "status",
            "status_pending": "pending",
            "status_paid": "paid",
            "status_partially_refunded": "partially_refunded",
            "status_refunded": "refunded",
        },
        "currencies": ["USD", "INR"],
        "max_amount_minor": 5_000_000,
        "success_urls": ["https://shop.example.com/paid"],
        "cancel_urls": ["https://shop.example.com/cart"],
        "roles": {
            "create": ["customer"],
            "read": ["customer"],
            "read_all": ["admin"],
            "refund": ["admin"],
            "operate": ["admin"],
        },
    }
    payments.update(payments_overrides)
    return {
        "project": {"name": "Shop", "slug": "shop"},
        "entities": [
            {
                "name": "Order",
                "table_name": "orders",
                "plural_path": "orders",
                "fields": [
                    {"name": "total", "type": "decimal", "required": True, "min_value": 0.01},
                    {"name": "currency", "type": "string", "required": True, "max_length": 3},
                    {
                        "name": "status",
                        "type": "enum",
                        "required": True,
                        "default": "pending",
                        "enum_values": [
                            "pending",
                            "paid",
                            "partially_refunded",
                            "refunded",
                            "cancelled",
                        ],
                    },
                ],
            }
        ],
        "relations": [],
        "auth": {
            "enabled": True,
            "app_url": "https://shop.example.com",
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "use_tls": True,
                "from_email": "noreply@shop.example.com",
                "from_name": "Shop",
            },
            "roles": [
                {"name": "admin", "label": "Admin"},
                {"name": "customer", "label": "Customer", "is_default": True},
            ],
            # Payers (customers) read orders; only staff write them: nobody who pays sets a price.
            "permissions": [
                {
                    "entity": "Order",
                    "operation": op,
                    "roles": ["customer", "admin"] if op in READ_OPS else ["admin"],
                }
                for op in OPS
            ],
        },
        "payments": payments,
    }


def issues_for(mutate: Callable[[dict[str, Any]], None] | None = None) -> list[ValidationIssue]:
    data = copy.deepcopy(base_spec())
    if mutate is not None:
        mutate(data)
    return validate(Spec.model_validate(data))


def codes(issues: list[ValidationIssue]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in issues}


def pay(**changes: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"].update(changes)

    return mutate


def payable(**changes: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"]["payable"].update(changes)

    return mutate


def test_a_complete_payments_block_is_valid() -> None:
    assert issues_for() == []


def test_no_payments_block_is_valid() -> None:
    data = base_spec()
    del data["payments"]
    assert validate(Spec.model_validate(data)) == []


def test_a_disabled_block_only_gets_structural_checks() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"] = {"enabled": False}

    assert issues_for(mutate) == []

    def bad_enum(d: dict[str, Any]) -> None:
        d["payments"] = {"enabled": False, "provider": "venmo"}

    assert ("payments.provider", "invalid_value") in codes(issues_for(bad_enum))


def test_payments_need_auth() -> None:
    def mutate(d: dict[str, Any]) -> None:
        del d["auth"]

    assert ("payments", "requires_auth") in codes(issues_for(mutate))


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"provider": "venmo"}, ("payments.provider", "invalid_value")),
        ({"currencies": []}, ("payments.currencies", "required")),
        ({"currencies": ["usd"]}, ("payments.currencies[0]", "invalid_value")),
        ({"currencies": ["KWD"]}, ("payments.currencies[0]", "unsupported")),
        ({"currencies": ["HUF"]}, ("payments.currencies[0]", "unsupported")),
        ({"currencies": ["USD", "USD"]}, ("payments.currencies[1]", "duplicate_name")),
        ({"max_amount_minor": 0}, ("payments.max_amount_minor", "out_of_range")),
        ({"max_amount_minor": 10**9}, ("payments.max_amount_minor", "out_of_range")),
        ({"success_urls": []}, ("payments.success_urls", "required")),
        ({"cancel_urls": []}, ("payments.cancel_urls", "required")),
        (
            {"success_urls": ["http://shop.example.com/x"]},
            ("payments.success_urls[0]", "invalid_value"),
        ),
        (
            {"success_urls": ["https://*.example.com/x"]},
            ("payments.success_urls[0]", "invalid_value"),
        ),
        (
            {"cancel_urls": ["https://user:pw@shop.example.com/"]},
            ("payments.cancel_urls[0]", "invalid_value"),
        ),
        (
            {"cancel_urls": ["https://shop.example.com/#frag"]},
            ("payments.cancel_urls[0]", "invalid_value"),
        ),
        (
            {"success_urls": ["https://a.example.com/", "https://a.example.com/"]},
            ("payments.success_urls", "duplicate_name"),
        ),
        (
            {"refund_approval_threshold_minor": 10**9},
            ("payments.refund_approval_threshold_minor", "out_of_range"),
        ),
    ],
)
def test_block_level_rules(changes: dict[str, Any], expected: tuple[str, str]) -> None:
    assert expected in codes(issues_for(pay(**changes)))


def test_localhost_may_use_http() -> None:
    assert issues_for(pay(success_urls=["http://localhost:3000/paid"])) == []


def test_razorpay_only_supports_its_own_currency_list() -> None:
    assert ("payments.currencies[0]", "unsupported") in codes(
        issues_for(pay(provider="razorpay", currencies=["CHF"]))
    )

    def inr(d: dict[str, Any]) -> None:
        d["payments"].update(provider="razorpay", currencies=["INR"])
        d["payments"]["payable"].update(currency_field=None, currency="INR")
        d["entities"][0]["fields"][0]["min_value"] = 1

    assert issues_for(inr) == []


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"entity": "Nope"}, ("payments.payable.entity", "unknown_entity")),
        ({"amount_field": "nope"}, ("payments.payable.amount_field", "unknown_field")),
        ({"amount_field": "currency"}, ("payments.payable.amount_field", "invalid_value")),
        ({"currency_field": "total"}, ("payments.payable.currency_field", "invalid_value")),
        ({"currency_field": "nope"}, ("payments.payable.currency_field", "unknown_field")),
        ({"currency": "USD"}, ("payments.payable", "invalid_value")),  # both currency forms
        ({"status_field": "total"}, ("payments.payable.status_field", "invalid_value")),
        ({"status_field": "nope"}, ("payments.payable.status_field", "unknown_field")),
        ({"status_paid": "unknown"}, ("payments.payable.status_paid", "invalid_value")),
        ({"status_refunded": "paid"}, ("payments.payable", "invalid_value")),  # not distinct
    ],
)
def test_payable_rules(changes: dict[str, Any], expected: tuple[str, str]) -> None:
    assert expected in codes(issues_for(payable(**changes)))


def test_a_fixed_currency_must_be_on_the_allowlist() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"]["payable"].update({"currency_field": None, "currency": "EUR"})

    assert ("payments.payable.currency", "invalid_value") in codes(issues_for(mutate))

    def fixed(d: dict[str, Any]) -> None:
        d["payments"]["payable"].update({"currency_field": None, "currency": "USD"})

    assert issues_for(fixed) == []


def test_the_payable_needs_a_payments_payable_block() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"]["payable"] = None

    assert ("payments.payable", "required") in codes(issues_for(mutate))


def test_the_amount_must_be_strictly_positive() -> None:
    def mutate(d: dict[str, Any]) -> None:
        del d["entities"][0]["fields"][0]["min_value"]

    assert ("payments.payable.amount_field", "invalid_value") in codes(issues_for(mutate))


def test_the_amount_and_status_fields_must_be_required() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"][0]["required"] = False
        d["entities"][0]["fields"][2]["required"] = False

    found = codes(issues_for(mutate))
    assert ("payments.payable.amount_field", "invalid_value") in found
    assert ("payments.payable.status_field", "invalid_value") in found


def test_the_currency_field_must_be_exactly_three_characters() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"][1]["max_length"] = 10

    assert ("payments.payable.currency_field", "invalid_value") in codes(issues_for(mutate))


# --- the payable entity must not be reachable by everyone --------------------------------


def test_every_operation_of_the_payable_entity_needs_a_role() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["permissions"] = [
            p for p in d["auth"]["permissions"] if p["operation"] != "update"
        ]

    found = issues_for(mutate)
    assert ("payments.payable.entity", "public_operation") in codes(found)
    assert any("Order.update" in i.message for i in found)


def test_an_empty_role_list_counts_as_public() -> None:
    def mutate(d: dict[str, Any]) -> None:
        for p in d["auth"]["permissions"]:
            if p["operation"] == "delete":
                p["roles"] = []

    assert ("payments.payable.entity", "public_operation") in codes(issues_for(mutate))


def test_the_payable_entity_needs_the_get_operation() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][0]["options"] = {"operations": ["list", "create"]}
        d["auth"]["permissions"] = [
            p for p in d["auth"]["permissions"] if p["operation"] in ("list", "create")
        ]

    assert ("payments.payable.entity", "invalid_value") in codes(issues_for(mutate))


def test_in_a_multi_tenant_project_the_payable_needs_the_tenant_rule() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["multi_tenant"] = True

    assert ("payments.payable.entity", "not_tenant_scoped") in codes(issues_for(mutate))

    def scoped(d: dict[str, Any]) -> None:
        d["auth"]["multi_tenant"] = True
        for p in d["auth"]["permissions"]:
            p["row_rule"] = "tenant"

    assert issues_for(scoped) == []


# --- roles ------------------------------------------------------------------------------


def test_roles_must_exist_and_create_and_read_cannot_be_empty() -> None:
    def unknown(d: dict[str, Any]) -> None:
        d["payments"]["roles"]["refund"] = ["ghost"]

    assert ("payments.roles.refund", "unknown_reference") in codes(issues_for(unknown))

    def empty(d: dict[str, Any]) -> None:
        d["payments"]["roles"]["create"] = []
        d["payments"]["roles"]["read"] = []

    found = codes(issues_for(empty))
    assert ("payments.roles.create", "required") in found
    assert ("payments.roles.read", "required") in found


def test_empty_optional_roles_are_allowed_and_mean_nobody() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"]["roles"]["refund"] = []
        d["payments"]["roles"]["operate"] = []
        d["payments"]["roles"]["read_all"] = []

    assert issues_for(mutate) == []


def test_a_refund_threshold_needs_refund_and_approver_roles() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"]["refund_approval_threshold_minor"] = 50_000
        d["payments"]["roles"]["refund"] = []

    found = codes(issues_for(mutate))
    assert ("payments.roles.refund", "required") in found
    assert ("payments.roles.approve_refund", "required") in found

    def ok(d: dict[str, Any]) -> None:
        d["payments"]["refund_approval_threshold_minor"] = 50_000
        d["payments"]["roles"]["approve_refund"] = ["admin"]

    assert issues_for(ok) == []


def test_duplicate_roles_are_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"]["roles"]["create"] = ["customer", "customer"]

    assert ("payments.roles.create", "duplicate_name") in codes(issues_for(mutate))


# --- security floors and ceilings --------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("webhook_tolerance_seconds", 5),
        ("webhook_tolerance_seconds", 3600),
        ("webhook_max_body_bytes", 10),
        ("webhook_max_body_bytes", 10**9),
        ("idempotency_ttl_hours", 1),
        ("idempotency_ttl_hours", 10_000),
        ("audit_retention_days", 30),
        ("audit_retention_days", 10**6),
    ],
)
def test_security_knobs_have_floors_and_ceilings(name: str, value: int) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"]["security"] = {name: value}

    assert (f"payments.security.{name}", "out_of_range") in codes(issues_for(mutate))


def test_security_knobs_inside_their_range_are_accepted() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"]["security"] = {
            "webhook_tolerance_seconds": 120,
            "webhook_max_body_bytes": 65536,
            "idempotency_ttl_hours": 72,
            "audit_retention_days": 3650,
            "webhook_ip_allowlist_enabled": True,
        }

    assert issues_for(mutate) == []


# --- scale ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"profile": "huge"}, ("payments.scale.profile", "invalid_value")),
        ({"availability": "always"}, ("payments.scale.availability", "invalid_value")),
        ({"webhook_mode": "later"}, ("payments.scale.webhook_mode", "invalid_value")),
        ({"api_replicas": 0}, ("payments.scale.api_replicas", "out_of_range")),
        ({"server_workers": 1000}, ("payments.scale.server_workers", "out_of_range")),
        ({"worker_concurrency": 0}, ("payments.scale.worker_concurrency", "out_of_range")),
        ({"pool_size": 0}, ("payments.scale.pool_size", "out_of_range")),
        (
            {"peak_payments_per_minute": 0},
            ("payments.scale.peak_payments_per_minute", "out_of_range"),
        ),
        ({"db_max_connections": 3}, ("payments.scale.db_max_connections", "out_of_range")),
        (
            {"webhook_events_retention_days": 1},
            ("payments.scale.webhook_events_retention_days", "out_of_range"),
        ),
        ({"jobs_retention_days": 0}, ("payments.scale.jobs_retention_days", "out_of_range")),
    ],
)
def test_scale_rules(changes: dict[str, Any], expected: tuple[str, str]) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"]["scale"] = changes

    assert expected in codes(issues_for(mutate))


def test_a_plan_that_does_not_fit_the_database_must_use_pgbouncer() -> None:
    crowded = {"profile": "large", "availability": "ha", "db_max_connections": 40}

    def without(d: dict[str, Any]) -> None:
        d["payments"]["scale"] = dict(crowded)

    assert ("payments.scale", "connection_budget") in codes(issues_for(without))

    def with_pooler(d: dict[str, Any]) -> None:
        d["payments"]["scale"] = {**crowded, "pgbouncer": True}

    assert issues_for(with_pooler) == []


# --- table names --------------------------------------------------------------------------


def test_entities_cannot_take_the_payment_table_names() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"].append(
            {"name": "Ledger", "table_name": "pay_payments", "plural_path": "ledgers", "fields": []}
        )

    assert ("entities[1].table_name", "duplicate_name") in codes(issues_for(mutate))

    # With payments switched off the names are free again.
    def off(d: dict[str, Any]) -> None:
        d["payments"] = {"enabled": False}
        d["entities"].append(
            {"name": "Ledger", "table_name": "pay_payments", "plural_path": "ledgers", "fields": []}
        )

    assert issues_for(off) == []


def test_an_entity_cannot_take_the_payments_route() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"].append(
            {"name": "Payment", "table_name": "pays", "plural_path": "payments", "fields": []}
        )

    assert ("entities[1].plural_path", "reserved_word") in codes(issues_for(mutate))


def test_razorpay_needs_an_amount_of_at_least_one_unit() -> None:
    def low(d: dict[str, Any]) -> None:
        d["payments"]["provider"] = "razorpay"
        d["payments"]["currencies"] = ["INR"]
        d["payments"]["payable"]["currency_field"] = None
        d["payments"]["payable"]["currency"] = "INR"

    assert ("payments.payable.amount_field", "invalid_value") in codes(issues_for(low))

    def fine(d: dict[str, Any]) -> None:
        low(d)
        d["entities"][0]["fields"][0]["min_value"] = 1

    assert issues_for(fine) == []


# --- payers must not be able to set the price --------------------------------------------------


def open_to_customers(op: str) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        for p in d["auth"]["permissions"]:
            if p["operation"] == op:
                p["roles"] = ["customer", "admin"]

    return mutate


@pytest.mark.parametrize("op", ["create", "replace", "update", "delete"])
def test_payers_cannot_write_the_item_they_pay_for(op: str) -> None:
    found = issues_for(open_to_customers(op))
    assert ("payments.payable.entity", "payer_can_set_amount") in codes(found)
    assert any(f"Order.{op}" in i.message for i in found)


def test_the_risk_can_be_accepted_explicitly() -> None:
    def accept(d: dict[str, Any]) -> None:
        open_to_customers("update")(d)
        d["payments"]["security"] = {"allow_payer_edits": True}

    assert issues_for(accept) == []


def test_the_default_roles_count_as_payers() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["payments"]["roles"]["create"] = ["admin"]  # a different payer role ...
        d["auth"]["roles"].append({"name": "member", "label": "Member", "is_default": True})
        for p in d["auth"]["permissions"]:
            if p["operation"] == "update":
                p["roles"] = ["member"]  # ... but everyone holds the default role

    assert ("payments.payable.entity", "payer_can_set_amount") in codes(issues_for(mutate))


def test_inherited_roles_count_as_payers() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["roles"] = [
            {"name": "staff", "label": "Staff"},
            {"name": "admin", "label": "Admin"},
            {"name": "customer", "label": "Customer", "is_default": True, "inherits_from": "staff"},
        ]
        for p in d["auth"]["permissions"]:
            if p["operation"] == "update":
                p["roles"] = ["staff"]  # customers inherit staff's rights

    assert ("payments.payable.entity", "payer_can_set_amount") in codes(issues_for(mutate))
