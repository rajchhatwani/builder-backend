"""What only a human can enter, and what is still missing, for the MCP server (pure, no DB).

Never carries a secret value: only the NAMES of environment variables or fields and the place where
a person enters them. Names are grounded in the generator templates and in the dashboard's
`NextSteps` panel (frontend/src/components/NextSteps.tsx).
"""

from typing import Any

from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, invitations_enabled
from app.services.status_service import SECTION_LABELS, issue_area

MAX_MISSING_ITEMS = 50

_SIGN_IN = "Dashboard > Secure > Sign-in (credentials are stored encrypted on the server)"
_KEYCLOAK = "Dashboard > Secure > Keycloak, then the .env file of the generated project"
_PAYMENTS = (
    "Dashboard > Connect > Payments; the secrets go in the .env file of the generated project"
)
_STORAGE = (
    "Dashboard > Connect > File storage; the secrets go in the .env file of the generated project"
)
_DEPLOY = (
    "Dashboard > Ship > Deployment; the one-time cloud trust setup is in deploy/<cloud>/bootstrap"
)
_PROVIDERS = (
    "Dashboard > Connect > Provider integrations; each tenant admin stores credentials through "
    "the generated project's admin-only vault API"
)
_WEBHOOKS = (
    "Dashboard > Connect > Webhooks; the signing secrets are stored per endpoint through the "
    "generated project's admin-only vault API"
)

# Areas whose next step is a tool, and the tools that fix them.
_TOOLS_BY_AREA: dict[str, list[str]] = {
    "model": ["create_entity", "add_field", "add_relation", "apply_op"],
    "auth": ["set_auth_config"],
    "authorization": ["create_role", "set_permissions", "set_authorization"],
    "state_machines": ["apply_op"],
    "settings": ["apply_op"],
    "history": ["apply_op"],
    "hooks": ["apply_op"],
    "seed": ["apply_op"],
}
_HUMAN_AREAS = {"payments", "storage", "observability", "deployment", "documents"}

_INVITE_HINT = (
    "invite_only roles need SMTP + app_url; either set them later in the dashboard or use "
    "invite_only=false and self_assignable=false (an admin assigns the role)"
)


def _entry(
    id_: str,
    area: str,
    label: str,
    because: str,
    names: list[str],
    where: str,
    blocking: bool = False,
) -> dict[str, Any]:
    return {
        "id": id_,
        "area": area,
        "label": label,
        "needed_because": because,
        "names": names,
        "where_to_enter": where,
        "blocking": blocking,
    }


def _on(block: object | None) -> bool:
    return block is not None and bool(getattr(block, "enabled", True))


def _idp_secret_name(alias: str) -> str:
    return "KC_IDP_" + alias.upper().replace("-", "_") + "_CLIENT_SECRET"


def _sms_names(provider: str | None) -> list[str]:
    if provider == "twilio":
        return ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]
    if provider == "vonage":
        return ["VONAGE_API_KEY", "VONAGE_API_SECRET"]
    if provider == "aws_sns":
        return ["AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    return ["sms_provider"]


def _auth_entries(spec: Spec) -> list[dict[str, Any]]:
    auth = spec.auth
    if not _on(auth):
        return []
    assert auth is not None
    out: list[dict[str, Any]] = []
    keycloak = auth.provider == "keycloak" and auth.keycloak is not None
    if keycloak:
        assert auth.keycloak is not None
        kc = auth.keycloak
        own = kc.mode == "own"
        names = ["KEYCLOAK_PUBLIC_URL", "API_PUBLIC_URL"]
        if own:
            names += [
                "KEYCLOAK_DB_PASSWORD",
                "KC_BOOTSTRAP_ADMIN_USERNAME",
                "KC_BOOTSTRAP_ADMIN_PASSWORD",
            ]
        else:
            names += ["KEYCLOAK_ADMIN_USERNAME", "KEYCLOAK_ADMIN_PASSWORD"]
        out.append(
            _entry(
                "auth_keycloak",
                "auth",
                "Keycloak connection and admin login",
                "sign-in is handled by Keycloak, which needs its address and an admin login",
                names,
                _KEYCLOAK,
            )
        )
        for idp in kc.identity_providers:
            out.append(
                _entry(
                    f"auth_sso_{idp.alias}",
                    "auth",
                    f"Client secret of the {idp.display_name or idp.alias} login (SSO)",
                    f"the {idp.type} identity provider '{idp.alias}' needs the client secret "
                    "from the provider's console",
                    [_idp_secret_name(idp.alias)],
                    _KEYCLOAK,
                )
            )
    else:
        if auth.jwt_algorithm == "RS256":
            out.append(
                _entry(
                    "auth_jwt_key",
                    "auth",
                    "JWT signing key (RS256)",
                    "access tokens are signed with an RSA private key",
                    ["AUTH_JWT_PRIVATE_KEY"],
                    "The .env file of the generated project (generate with python -m app.auth.keys)",
                )
            )
        else:
            out.append(
                _entry(
                    "auth_jwt_key",
                    "auth",
                    "JWT signing secret (HS256)",
                    "access tokens are signed with a secret of 32+ characters",
                    ["AUTH_JWT_SECRET"],
                    "The .env file of the generated project (generate with python -m app.auth.keys)",
                )
            )
        if auth.token_store == "redis":
            out.append(
                _entry(
                    "auth_redis",
                    "auth",
                    "Redis address for refresh tokens",
                    "the token store is redis",
                    ["REDIS_URL"],
                    "The .env file of the generated project",
                )
            )
    reset = auth.password_reset
    wants_email = (
        reset.email_magic_link
        or auth.registration.email_verification_required
        or (not keycloak and invitations_enabled(auth))
    )
    if wants_email or (keycloak and auth.smtp is not None):
        names = ["SMTP_USERNAME", "SMTP_PASSWORD"]
        if auth.smtp is None:
            names = ["smtp.host", "smtp.from_email", "smtp.from_name", *names]
        out.append(
            _entry(
                "auth_smtp",
                "auth",
                "Email (SMTP) login for sign-in emails",
                "magic links, email verification, password resets and invitations are sent "
                "by email",
                names,
                _SIGN_IN,
                blocking=auth.smtp is None and not keycloak,
            )
        )
    if auth.sms_provider and not keycloak:
        out.append(
            _entry(
                "auth_sms",
                "auth",
                f"SMS provider credentials ({auth.sms_provider})",
                "one-time codes are sent by SMS",
                _sms_names(auth.sms_provider),
                _SIGN_IN,
                blocking=auth.sms is None,
            )
        )
    elif reset.sms_otp and not keycloak:
        out.append(
            _entry(
                "auth_sms",
                "auth",
                "SMS provider and credentials",
                "sms_otp is on but no SMS provider is chosen",
                ["sms_provider", "sms.from_number"],
                _SIGN_IN,
                blocking=True,
            )
        )
    return out


def _payments_entry(spec: Spec) -> list[dict[str, Any]]:
    pay = spec.payments
    if not _on(pay):
        return []
    assert pay is not None
    if pay.provider == "razorpay":
        names = ["RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRETS"]
    else:
        names = ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRETS"]
    if pay.security.webhook_ip_allowlist_enabled:
        names.append("PAYMENTS_WEBHOOK_IP_ALLOWLIST")
    return [
        _entry(
            "payments_provider",
            "payments",
            f"Payment provider API key and webhook signing secret ({pay.provider})",
            "the generated payments module calls the provider and verifies its webhooks",
            names,
            _PAYMENTS,
        )
    ]


def _storage_entry(spec: Spec) -> list[dict[str, Any]]:
    st = spec.storage
    if not _on(st):
        return []
    assert st is not None
    names = ["STORAGE_ACCESS_KEY_ID", "STORAGE_SECRET_ACCESS_KEY"]
    if st.backend == "minio":
        names.append("STORAGE_ENDPOINT_URL")
    else:
        names.append("STORAGE_REGION")
    return [
        _entry(
            "storage_bucket",
            "storage",
            f"File storage credentials ({st.backend})",
            "uploads are written to an S3-compatible bucket",
            names,
            _STORAGE,
            blocking=not st.bucket,
        )
    ]


def _deployment_entry(spec: Spec) -> list[dict[str, Any]]:
    dep = spec.deployment
    if not _on(dep):
        return []
    assert dep is not None
    names = {
        "aws": ["AWS_ROLE_ARN"],
        "azure": ["AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"],
        "gcp": ["GCP_WORKLOAD_IDENTITY_PROVIDER", "GCP_SERVICE_ACCOUNT"],
    }.get(dep.cloud, [])
    return [
        _entry(
            "deployment_cloud",
            "deployment",
            f"Cloud trust setup ({dep.cloud})",
            "pipelines sign in with short-lived OIDC tokens; a person runs the one-time "
            "trust bootstrap and sets these as GitHub environment variables (no cloud "
            "credential is stored)",
            names,
            _DEPLOY,
            blocking=not dep.region or not dep.github_repo,
        )
    ]


def _providers_entries(spec: Spec) -> list[dict[str, Any]]:
    prov = spec.providers
    out: list[dict[str, Any]] = []
    if _on(prov) and prov is not None and prov.enabled:
        adapters = [f"{a.kind}:{a.name}" for a in prov.adapters if a.name != "emulator"]
        out.append(
            _entry(
                "providers_vault",
                "providers",
                "Provider API keys (email, sms, push and others)",
                "each tenant admin stores the credentials of the adapters it uses",
                adapters or ["adapters"],
                _PROVIDERS,
            )
        )
    notif = spec.notifications
    if _on(notif) and notif is not None and notif.enabled:
        out.append(
            _entry(
                "notifications_channels",
                "notifications",
                "Credentials of the notification channels",
                "notifications are sent through the provider adapters (email, sms, push)",
                sorted({c for t in notif.types for c in t.channels}) or ["channels"],
                _PROVIDERS,
                blocking=not (prov is not None and prov.enabled),
            )
        )
    hooks = spec.webhooks
    if _on(hooks) and hooks is not None and hooks.enabled:
        names = [f"inbound:{i.name}" for i in hooks.inbound] + ["outgoing endpoints"]
        out.append(
            _entry(
                "webhooks_signing",
                "webhooks",
                "Webhook signing secrets",
                "incoming webhooks are verified, outgoing ones are signed, with a stored secret",
                names,
                _WEBHOOKS,
                blocking=not (prov is not None and prov.enabled),
            )
        )
    return out


def _ai_entry(spec: Spec) -> list[dict[str, Any]]:
    ai = spec.packs.ai if spec.packs is not None else None
    gw = ai.gateway if ai is not None else None
    if gw is None:
        return []
    names = sorted({p.byo_key_env for p in gw.providers if p.byo_key_env})
    if not names:
        return []
    return [
        _entry(
            "packs_ai_keys",
            "packs",
            "AI model provider API keys",
            "the AI gateway reads each provider's key from the named environment variable",
            names,
            "The .env file of the generated project; see Dashboard > Connect > AI gateway settings",
        )
    ]


def secrets_needed(spec: Spec) -> list[dict[str, Any]]:
    """Everything only a human can enter for the features that are on. Names only, never values."""
    return [
        *_auth_entries(spec),
        *_payments_entry(spec),
        *_storage_entry(spec),
        *_deployment_entry(spec),
        *_providers_entries(spec),
        *_ai_entry(spec),
    ]


def _item(area: str, item: str, why: str, who: str, tools: list[str]) -> dict[str, Any]:
    return {"area": area, "item": item, "why": why, "who": who, "next_tools": tools}


def missing_items(spec: Spec, issues: list[ValidationIssue]) -> list[dict[str, Any]]:
    """The checklist of what a finished backend still lacks, model first, at most 50 items."""
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(entry: dict[str, Any]) -> None:
        key = (entry["area"], entry["item"])
        if key not in seen:
            seen.add(key)
            items.append(entry)

    if not spec.entities:
        add(
            _item(
                "model",
                "Add at least one entity",
                "A backend needs data to serve.",
                "tool",
                ["create_entity"],
            )
        )
    if not _on(spec.auth):
        add(
            _item(
                "auth",
                "Decide how people sign in (optional)",
                "The API has no user accounts yet; skip this if it does not need them.",
                "tool",
                ["set_auth_config"],
            )
        )
    elif (
        spec.auth is not None
        and not spec.auth.roles
        and (spec.auth.permissions or spec.authorization is not None)
    ):
        add(
            _item(
                "authorization",
                "Create the roles that permissions refer to",
                "Permissions or policies exist but auth.roles is empty.",
                "tool",
                ["create_role"],
            )
        )

    hint = False
    for issue in issues:
        area = issue_area(issue)
        if area in _HUMAN_AREAS:
            add(
                _item(
                    area,
                    f"Configure in the dashboard: {issue.message}",
                    f"{issue.path} ({issue.code})",
                    "human",
                    [],
                )
            )
        else:
            add(
                _item(
                    area,
                    issue.message,
                    f"{issue.path} ({issue.code})",
                    "tool",
                    list(_TOOLS_BY_AREA.get(area, _TOOLS_BY_AREA["model"])),
                )
            )
        text = f"{issue.path} {issue.message}".lower()
        if any(k in text for k in ("invite_only", "invitation", "smtp", "app_url")):
            hint = True
    if hint:
        add(
            _item(
                "authorization",
                _INVITE_HINT,
                "Invitations are sent by email and need a link back to the app.",
                "tool",
                ["update_role"],
            )
        )

    for entry in secrets_needed(spec):
        if entry["blocking"]:
            add(
                _item(
                    entry["area"], f"Enter: {entry['label']}", entry["needed_because"], "human", []
                )
            )

    order = {key: i for i, (key, _l) in enumerate(SECTION_LABELS)}
    items.sort(key=lambda it: order.get(it["area"], len(order)))  # stable: keeps input order
    return items[:MAX_MISSING_ITEMS]
