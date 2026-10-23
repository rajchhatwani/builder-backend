"""The `payments` feature: hosted-checkout payments, refunds, disputes, signed webhooks, a job queue
with workers, an audit trail and the deployment files sized for the expected load.

Only used when the spec has an enabled `payments` block (and auth). Nothing secret is ever
rendered: provider keys and webhook secrets are environment variables of the generated project.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core import currencies
from app.core.generator.base import FileTree
from app.core.generator.context import AccessCtx, ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.payments_sizing import PaymentsSizing, size
from app.core.spec_models import SpecPayments
from app.core.validation import uses_keycloak
from app.core.validation_payments import payments_active

_TEMPLATES = Path(__file__).parent / "templates"

_ROLE_NAMES = ("create", "read", "read_all", "refund", "approve_refund", "operate")

_VERBATIM = (
    "app/payments/__init__.py.tpl",
    "app/payments/audit.py.tpl",
    "app/payments/events.py.tpl",
    "app/payments/idempotency.py.tpl",
    "app/payments/jobs.py.tpl",
    "app/payments/lock.py.tpl",
    "app/payments/models.py.tpl",
    "app/payments/money.py.tpl",
    "app/payments/providers/__init__.py.tpl",
    "app/payments/providers/base.py.tpl",
    "app/payments/reconcile.py.tpl",
    "app/payments/router.py.tpl",
    "app/payments/schemas.py.tpl",
    "app/payments/service.py.tpl",
    "app/payments/state.py.tpl",
    "app/payments/worker.py.tpl",
)
_RENDERED = (
    "app/payments/config.py.j2",
    "app/payments/payable.py.j2",
    "alembic/versions/0003_payments.py.j2",
    "tests/payments_support.py.j2",
    "tests/test_payments_flow.py.j2",
    "tests/test_payments_security.py.j2",
)
_DEPLOY_RENDERED = (
    "deploy/DEPLOYMENT.md.j2",
    "deploy/compose.worker.yml.j2",
    "deploy/sql/roles.sql.j2",
)
_K8S_RENDERED = (
    "deploy/k8s/api.yaml.j2",
    "deploy/k8s/jobs.yaml.j2",
    "deploy/k8s/kustomization.yaml.j2",
    "deploy/k8s/network-policy.yaml.j2",
    "deploy/k8s/worker.yaml.j2",
)

# Pinned, never "latest": an audit needs to know exactly which version ships.
PGBOUNCER_IMAGE = "edoburu/pgbouncer:v1.25.1-p0"
MAX_UVICORN_WORKERS_ONE_HOST = 16


# What differs between providers in the rendered text (env variable names, wording, events to enable).
PROVIDERS: dict[str, SimpleNamespace] = {
    "stripe": SimpleNamespace(
        name="stripe",
        title="Stripe",
        env_prefix="STRIPE",
        api_base="https://api.stripe.com",
        key_envs=("STRIPE_SECRET_KEY",),
        secret_envs=("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRETS"),
        webhook_secret_env="STRIPE_WEBHOOK_SECRETS",
        key_example="sk_test_...",
        checkout_name="Stripe Checkout",
        events=(
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
            "checkout.session.async_payment_failed",
            "checkout.session.expired",
            "charge.refunded",
            "refund.created",
            "refund.updated",
            "charge.refund.updated",
            "charge.dispute.created",
            "charge.dispute.updated",
            "charge.dispute.closed",
        ),
    ),
    "razorpay": SimpleNamespace(
        name="razorpay",
        title="Razorpay",
        env_prefix="RAZORPAY",
        api_base="https://api.razorpay.com",
        key_envs=("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"),
        secret_envs=("RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRETS"),
        webhook_secret_env="RAZORPAY_WEBHOOK_SECRETS",
        key_example="rzp_test_...",
        checkout_name="Razorpay Payment Links",
        events=(
            "payment_link.paid",
            "payment_link.expired",
            "payment_link.cancelled",
            "refund.created",
            "refund.processed",
            "refund.failed",
            "payment.dispute.created",
            "payment.dispute.won",
            "payment.dispute.lost",
            "payment.dispute.closed",
            "payment.dispute.under_review",
            "payment.dispute.action_required",
        ),
    ),
}


def active(project: ProjectCtx) -> SpecPayments | None:
    """The payments block when payments are switched on (and auth is, which they need)."""
    if project.auth is None or not payments_active(project.spec):
        return None
    return project.spec.payments


def sizing_for(pay: SpecPayments) -> PaymentsSizing:
    return size(pay.scale)


def _access_args(access: AccessCtx | None) -> str:
    """Keyword arguments for build_access() that reproduce the payable's `get` rules."""
    if access is None:
        return ""
    parts: list[str] = []
    if access.roles:
        parts.append(f"roles={tuple(access.roles)!r}")
    if access.owner:
        parts.append("owner=True")
    if access.admin_sees_all:
        parts.append("admin_sees_all=True")
    if access.match is not None:
        parts.append(f"match=({access.match[0]!r}, {access.match[1]})")
    if access.tenant:
        parts.append("tenant=True")
    return (", " + ", ".join(parts)) if parts else ""


class PaymentsModule:
    name = "payments"

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def context(self, project: ProjectCtx, pay: SpecPayments) -> dict[str, Any]:
        assert pay.payable is not None
        entity = project.entity_by_name[pay.payable.entity]
        get_access = next((a for a in entity.access if a.op == "get"), None)
        create_access = next((a for a in entity.access if a.op == "create"), None)
        payable = SimpleNamespace(
            entity=entity.name,
            model=entity.name,
            table=entity.table,
            path=entity.path,
            soft_delete=entity.soft_delete,
            owned=entity.owned,
            amount_field=pay.payable.amount_field,
            currency=pay.payable.currency,
            currency_field=pay.payable.currency_field,
            status_field=pay.payable.status_field,
            status_pending=pay.payable.status_pending,
            status_paid=pay.payable.status_paid,
            status_partially_refunded=pay.payable.status_partially_refunded,
            status_refunded=pay.payable.status_refunded,
        )
        order_fields: dict[str, Any] = {pay.payable.status_field: pay.payable.status_pending}
        if pay.payable.currency_field is not None:
            order_fields[pay.payable.currency_field] = pay.currencies[0]
        status_values = {
            pay.payable.status_pending,
            pay.payable.status_paid,
            pay.payable.status_partially_refunded,
            pay.payable.status_refunded,
        }
        other_status = next(
            (
                value
                for e in project.spec.entities
                if e.name == pay.payable.entity
                for f in e.fields
                if f.name == pay.payable.status_field
                for value in (f.enum_values or [])
                if value not in status_values
            ),
            None,
        )
        exponents = {code: currencies.EXPONENTS[code] for code in sorted(pay.currencies)}
        return {
            "p": pay,
            "prov": PROVIDERS[pay.provider],
            "payable": payable,
            "access_args": _access_args(get_access),
            "multi_tenant": bool(project.auth is not None and project.auth.multi_tenant),
            "exponents_literal": repr(exponents),
            "roles": pay.roles.model_dump(),
            "role_names": _ROLE_NAMES,
            "sizing": sizing_for(pay),
            "audit_days": pay.security.audit_retention_days,
            "order_fields": repr(order_fields),
            "creator_roles": repr(tuple(create_access.roles) if create_access else ()),
            "payer_edits": pay.security.allow_payer_edits,
            "other_status": other_status,
            "name": project.name,
            "slug": project.slug,
            "slug_sql": project.slug.replace("-", "_"),
            "kc": uses_keycloak(project.auth),
            "pgbouncer_image": PGBOUNCER_IMAGE,
            "single_host_workers": min(
                sizing_for(pay).api_replicas * sizing_for(pay).server_workers,
                MAX_UVICORN_WORKERS_ONE_HOST,
            ),
            "all_roles": repr(tuple(r.name for r in (project.auth.roles if project.auth else ()))),
        }

    def render(self, project: ProjectCtx) -> FileTree:
        pay = active(project)
        if pay is None:
            return {}
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in (*_VERBATIM, f"app/payments/providers/{pay.provider}.py.tpl")
        }
        fake = f"tests/fake_{pay.provider}.py"
        files[fake] = read_verbatim(_TEMPLATES, fake + ".tpl")
        context = self.context(project, pay)
        templates = _RENDERED + _DEPLOY_RENDERED + (_K8S_RENDERED if pay.scale.kubernetes else ())
        for template in templates:
            files[template.rsplit(".", 1)[0]] = render_template(self._env, template, **context)
        return files
