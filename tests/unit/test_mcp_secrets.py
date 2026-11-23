"""Pure tests for app.services.mcp_secrets: names and places only, never values."""

import json
import re
from typing import Any

from app.core.spec_models import Spec
from app.core.validation import ValidationIssue
from app.services.mcp_secrets import MAX_MISSING_ITEMS, missing_items, secrets_needed

KEYS = {"id", "area", "label", "needed_because", "names", "where_to_enter", "blocking"}
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$|^[A-Za-z][A-Za-z0-9_.:]*( [a-z]+)?$")


def _spec(**extra: Any) -> Spec:
    base: dict[str, Any] = {"project": {"name": "Demo", "slug": "demo"}}
    return Spec.model_validate({**base, **extra})


def test_empty_spec_needs_no_secrets() -> None:
    assert secrets_needed(_spec()) == []


def test_payments_names_only() -> None:
    items = secrets_needed(_spec(payments={"provider": "stripe"}))
    pay = next(i for i in items if i["id"] == "payments_provider")
    assert "STRIPE_SECRET_KEY" in pay["names"]
    assert "STRIPE_WEBHOOK_SECRETS" in pay["names"]
    assert not any(i["area"] == "payments" for i in secrets_needed(_spec()))


def test_razorpay_names() -> None:
    items = secrets_needed(_spec(payments={"provider": "razorpay"}))
    assert "RAZORPAY_KEY_SECRET" in items[0]["names"]


def test_smtp_entry_blocking_until_configured() -> None:
    no_smtp = secrets_needed(_spec(auth={}))
    smtp = next(i for i in no_smtp if i["id"] == "auth_smtp")
    assert smtp["blocking"] is True
    configured = _spec(
        auth={"smtp": {"host": "smtp.example.com", "from_email": "a@b.co", "from_name": "A"}}
    )
    smtp2 = next(i for i in secrets_needed(configured) if i["id"] == "auth_smtp")
    assert smtp2["blocking"] is False
    assert smtp2["names"] == ["SMTP_USERNAME", "SMTP_PASSWORD"]
    assert "Sign-in" in smtp2["where_to_enter"]


def test_sms_and_keycloak_sso_names() -> None:
    sms = _spec(
        auth={
            "sms_provider": "twilio",
            "sms": {"from_number": "+14155550123"},
            "password_reset": {"email_magic_link": False, "sms_otp": True},
            "registration": {"email_verification_required": False},
        }
    )
    assert any("TWILIO_AUTH_TOKEN" in i["names"] for i in secrets_needed(sms))
    kc = _spec(
        auth={
            "provider": "keycloak",
            "keycloak": {
                "realm": "r",
                "api_client_id": "api",
                "web_client_id": "web",
                "identity_providers": [{"alias": "my-google", "type": "google", "client_id": "x"}],
            },
        }
    )
    names = [n for i in secrets_needed(kc) for n in i["names"]]
    assert "KC_IDP_MY_GOOGLE_CLIENT_SECRET" in names


def test_storage_and_ai_and_deployment() -> None:
    spec = _spec(
        storage={"bucket": "b"},
        deployment={"cloud": "aws", "region": "eu-west-1", "github_repo": "o/r"},
        packs={"ai": {"gateway": {"providers": [{"name": "p", "byo_key_env": "MY_LLM_KEY"}]}}},
    )
    by_id = {i["id"]: i for i in secrets_needed(spec)}
    assert "STORAGE_SECRET_ACCESS_KEY" in by_id["storage_bucket"]["names"]
    assert by_id["storage_bucket"]["blocking"] is False
    assert by_id["deployment_cloud"]["names"] == ["AWS_ROLE_ARN"]
    assert by_id["packs_ai_keys"]["names"] == ["MY_LLM_KEY"]


def test_shape_and_names_have_no_values() -> None:
    spec = _spec(
        auth={},
        payments={},
        storage={},
        deployment={},
        providers={"enabled": True, "adapters": [{"kind": "email", "name": "sendgrid"}]},
        webhooks={"enabled": True, "inbound": [{"name": "stripe_in"}]},
    )
    items = secrets_needed(spec)
    assert items
    for item in items:
        assert set(item) == KEYS
        assert isinstance(item["blocking"], bool)
        assert item["where_to_enter"]
        for name in item["names"]:
            assert "=" not in name
            assert NAME_RE.match(name), name


def test_secret_looking_string_never_leaks() -> None:
    fake = "sk_live_FAKE0123456789secretvalue"
    spec = _spec(
        project={"name": fake, "slug": "demo", "description": fake},
        auth={
            "app_name": fake,
            "smtp": {"host": "smtp.example.com", "from_email": "a@b.co", "from_name": fake},
        },
        payments={"currencies": ["USD"], "success_urls": [f"https://x.example/{fake}"]},
        storage={"bucket": fake},
        deployment={"github_repo": fake, "region": "r"},
    )
    issues = [ValidationIssue(path="auth", code="required", message="no smtp")]
    blob = json.dumps([secrets_needed(spec), missing_items(spec, issues)])
    assert fake not in blob


def test_missing_items_order_and_who() -> None:
    issues = [
        ValidationIssue(path="payments.currencies", code="required", message="pick a currency"),
        ValidationIssue(path="entities[0].fields", code="required", message="needs a field"),
        ValidationIssue(path="auth.roles[0]", code="invalid_value", message="bad role"),
    ]
    items = missing_items(_spec(), issues)
    areas = [i["area"] for i in items]
    assert areas == ["model", "model", "auth", "authorization", "payments"]
    assert items[0]["item"] == "Add at least one entity"
    assert items[0]["next_tools"] == ["create_entity"]
    assert items[1]["next_tools"] == ["create_entity", "add_field", "add_relation", "apply_op"]
    assert items[2]["who"] == "tool" and items[2]["next_tools"] == ["set_auth_config"]
    pay = items[-1]
    assert pay["who"] == "human" and pay["next_tools"] == []
    assert pay["item"].startswith("Configure in the dashboard")
    for it in items:
        assert set(it) == {"area", "item", "why", "who", "next_tools"}


def test_invite_only_hint_and_blocking_secret_item() -> None:
    issues = [
        ValidationIssue(
            path="auth.roles",
            code="required",
            message="invitations are sent by email, so smtp must be configured",
        )
    ]
    spec = _spec(
        entities=[{"name": "Thing", "table_name": "things", "plural_path": "things", "fields": []}],
        auth={"roles": [{"name": "admin", "label": "Admin", "invite_only": True}]},
    )
    items = missing_items(spec, issues)
    hint = [i for i in items if i["item"].startswith("invite_only roles need SMTP")]
    assert len(hint) == 1
    assert hint[0]["who"] == "tool" and hint[0]["next_tools"] == ["update_role"]
    assert any(i["who"] == "human" and "SMTP" in i["item"] for i in items)
    assert missing_items(spec, issues) == items  # deterministic


def test_missing_items_capped() -> None:
    issues = [
        ValidationIssue(path=f"entities[{n}]", code="x", message=f"problem {n}") for n in range(80)
    ]
    assert len(missing_items(_spec(), issues)) == MAX_MISSING_ITEMS
