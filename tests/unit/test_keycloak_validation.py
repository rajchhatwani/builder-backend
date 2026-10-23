"""Validation rules for a project whose auth provider is Keycloak. Pure Python."""

from collections.abc import Callable
from typing import Any

import pytest

from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, redirect_uri_problem, validate

TENANT = "11111111-2222-3333-4444-555555555555"


def keycloak_block(**overrides: Any) -> dict[str, Any]:
    block: dict[str, Any] = {
        "mode": "own",
        "realm": "shop",
        "api_client_id": "shop-api",
        "web_client_id": "shop-web",
        "redirect_uris": ["http://localhost:3000/"],
        "identity_providers": [],
    }
    block.update(overrides)
    return block


def kc_spec(**auth_overrides: Any) -> dict[str, Any]:
    auth: dict[str, Any] = {
        "enabled": True,
        "provider": "keycloak",
        "keycloak": keycloak_block(),
        "registration": {"email_verification_required": False},
        "password_reset": {"email_magic_link": False},
        "roles": [{"name": "admin", "label": "Admin"}, {"name": "member", "label": "Member"}],
    }
    auth.update(auth_overrides)
    return {
        "project": {"name": "Shop", "slug": "shop"},
        "entities": [
            {
                "name": "Item",
                "table_name": "items",
                "plural_path": "items",
                "fields": [{"name": "title", "type": "string", "max_length": 100}],
            }
        ],
        "relations": [],
        "auth": auth,
    }


def issues_for(mutate: Callable[[dict[str, Any]], None] | None = None) -> list[ValidationIssue]:
    data = kc_spec()
    if mutate is not None:
        mutate(data)
    return validate(Spec.model_validate(data))


def codes(issues: list[ValidationIssue]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in issues}


def with_keycloak(**changes: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["keycloak"].update(changes)

    return mutate


def with_auth(**changes: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"].update(changes)

    return mutate


def test_minimal_keycloak_project_is_valid() -> None:
    assert issues_for() == []


def test_builtin_only_settings_are_not_demanded() -> None:
    # No app_url, no rate limits, no HS256 secret rules: Keycloak does these jobs.
    assert issues_for(with_auth(login_rate_limit="nonsense", jwt_algorithm="HS256")) == []


def test_keycloak_block_is_required_when_selected() -> None:
    found = issues_for(with_auth(keycloak=None))
    assert ("auth.keycloak", "required") in codes(found)


def test_block_is_only_deeply_checked_when_keycloak_is_selected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["provider"] = "builtin"
        d["auth"]["keycloak"]["realm"] = "NOT VALID"
        d["auth"]["smtp"] = None
        d["auth"]["registration"] = {"email_verification_required": False}
        d["auth"]["password_reset"] = {"email_magic_link": False}

    assert issues_for(mutate) == []


def test_unknown_provider_is_rejected() -> None:
    assert ("auth.provider", "invalid_value") in codes(issues_for(with_auth(provider="saml")))


def test_disabled_auth_skips_keycloak_rules() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"] = {"enabled": False, "provider": "keycloak", "keycloak": None}

    assert issues_for(mutate) == []


# --- realm and clients ------------------------------------------------------------------


@pytest.mark.parametrize("realm", ["Shop", "has space", "-lead", "a" * 64, "", "x_y"])
def test_bad_realm_names(realm: str) -> None:
    assert ("auth.keycloak.realm", "invalid_identifier") in codes(
        issues_for(with_keycloak(realm=realm))
    )


def test_master_realm_is_reserved() -> None:
    assert ("auth.keycloak.realm", "reserved_name") in codes(
        issues_for(with_keycloak(realm="master"))
    )


def test_clients_must_differ_and_be_well_formed() -> None:
    found = codes(issues_for(with_keycloak(web_client_id="shop-api")))
    assert ("auth.keycloak.web_client_id", "duplicate_name") in found
    found = codes(issues_for(with_keycloak(api_client_id="has space")))
    assert ("auth.keycloak.api_client_id", "invalid_identifier") in found


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password_min_length", 7),
        ("password_min_length", 129),
        ("session_idle_minutes", 4),
        ("session_max_hours", 0),
        ("session_max_hours", 721),
        ("audit_retention_days", 6),
        ("audit_retention_days", 3651),
    ],
)
def test_numeric_bounds(field: str, value: int) -> None:
    assert (f"auth.keycloak.{field}", "out_of_range") in codes(
        issues_for(with_keycloak(**{field: value}))
    )


def test_idle_timeout_cannot_exceed_session_length() -> None:
    found = codes(issues_for(with_keycloak(session_idle_minutes=121, session_max_hours=2)))
    assert ("auth.keycloak.session_idle_minutes", "invalid_range") in found


def test_mode_and_mfa_values() -> None:
    assert ("auth.keycloak.mode", "invalid_value") in codes(issues_for(with_keycloak(mode="x")))
    assert ("auth.keycloak.mfa", "invalid_value") in codes(issues_for(with_keycloak(mfa="x")))


# --- redirect URIs ----------------------------------------------------------------------


def test_at_least_one_redirect_uri() -> None:
    assert ("auth.keycloak.redirect_uris", "required") in codes(
        issues_for(with_keycloak(redirect_uris=[]))
    )


@pytest.mark.parametrize(
    "uri",
    [
        "https://app.example.com/*",
        "http://app.example.com/callback",
        "https://user:pw@app.example.com/",
        "https://app.example.com/#frag",
        "ftp://app.example.com/",
        "javascript:alert(1)",
        "https://app.example.com/ spaced",
        "https://app.example.com:99999/",
        "/relative",
        "https://",
    ],
)
def test_unsafe_redirect_uris(uri: str) -> None:
    assert redirect_uri_problem(uri) is not None
    assert ("auth.keycloak.redirect_uris[0]", "invalid_value") in codes(
        issues_for(with_keycloak(redirect_uris=[uri]))
    )


@pytest.mark.parametrize(
    "uri",
    [
        "https://app.example.com/",
        "https://app.example.com/auth/callback",
        "https://app.example.com:8443/cb",
        "http://localhost:3000/",
        "http://127.0.0.1:5173/cb",
        "http://[::1]:3000/",
    ],
)
def test_safe_redirect_uris(uri: str) -> None:
    assert redirect_uri_problem(uri) is None


def test_duplicate_redirect_uri() -> None:
    uri = "https://app.example.com/"
    found = codes(issues_for(with_keycloak(redirect_uris=[uri, uri])))
    assert ("auth.keycloak.redirect_uris[1]", "duplicate_name") in found


# --- identity providers -----------------------------------------------------------------


OIDC = {
    "issuer": "https://sso.example.com",
    "authorization_url": "https://sso.example.com/authorize",
    "token_url": "https://sso.example.com/token",
    "jwks_url": "https://sso.example.com/keys",
}


def idp(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"alias": "google", "type": "google", "client_id": "abc.apps.example"}
    base.update(overrides)
    return base


def test_valid_providers() -> None:
    providers = [
        idp(hosted_domain="example.com"),
        idp(alias="work", type="microsoft", tenant_id=TENANT),
        idp(alias="gh", type="github"),
        idp(alias="corp", type="oidc", **OIDC),
    ]
    assert issues_for(with_keycloak(identity_providers=providers)) == []


def test_microsoft_needs_a_guid_tenant() -> None:
    for tenant in (None, "common", "organizations", "not-a-guid"):
        found = codes(
            issues_for(
                with_keycloak(
                    identity_providers=[idp(alias="work", type="microsoft", tenant_id=tenant)]
                )
            )
        )
        assert ("auth.keycloak.identity_providers[0].tenant_id", "required") in found, tenant


def test_oidc_needs_its_endpoints_over_https() -> None:
    for name in ("issuer", "authorization_url", "token_url", "jwks_url"):
        provider = idp(alias="c", type="oidc", **{**OIDC, name: None})
        found = codes(issues_for(with_keycloak(identity_providers=[provider])))
        assert (f"auth.keycloak.identity_providers[0].{name}", "required") in found, name
        insecure = idp(alias="c", type="oidc", **{**OIDC, name: "http://sso.example.com/x"})
        found = codes(issues_for(with_keycloak(identity_providers=[insecure])))
        assert (f"auth.keycloak.identity_providers[0].{name}", "invalid_value") in found, name


def test_oidc_userinfo_is_optional_but_must_be_https() -> None:
    provider = idp(alias="c", type="oidc", **OIDC, userinfo_url="https://sso.example.com/me")
    assert issues_for(with_keycloak(identity_providers=[provider])) == []
    bad = idp(alias="c", type="oidc", **OIDC, userinfo_url="http://sso.example.com/me")
    found = codes(issues_for(with_keycloak(identity_providers=[bad])))
    assert ("auth.keycloak.identity_providers[0].userinfo_url", "invalid_value") in found


@pytest.mark.parametrize(
    "extra",
    [
        {"type": "github", "tenant_id": TENANT},
        {"type": "google", "issuer": "https://x.example.com"},
        {"type": "microsoft", "tenant_id": TENANT, "hosted_domain": "example.com"},
    ],
)
def test_fields_that_do_not_apply_to_a_provider_type(extra: dict[str, Any]) -> None:
    found = codes(issues_for(with_keycloak(identity_providers=[idp(alias="p", **extra)])))
    assert any(code == "not_applicable" for _, code in found)


def test_alias_rules() -> None:
    found = codes(
        issues_for(with_keycloak(identity_providers=[idp(alias="Bad Alias"), idp(alias="x")]))
    )
    assert ("auth.keycloak.identity_providers[0].alias", "invalid_identifier") in found
    found = codes(issues_for(with_keycloak(identity_providers=[idp(), idp()])))
    assert ("auth.keycloak.identity_providers[1].alias", "duplicate_name") in found


def test_google_hosted_domain_shape() -> None:
    found = codes(issues_for(with_keycloak(identity_providers=[idp(hosted_domain="not a domain")])))
    assert ("auth.keycloak.identity_providers[0].hosted_domain", "invalid_value") in found


def test_shared_realm_cannot_define_logins() -> None:
    found = codes(issues_for(with_keycloak(mode="shared", identity_providers=[idp()])))
    assert ("auth.keycloak.identity_providers", "not_applicable") in found


def test_too_many_providers() -> None:
    providers = [idp(alias=f"p{i}") for i in range(11)]
    found = codes(issues_for(with_keycloak(identity_providers=providers)))
    assert ("auth.keycloak.identity_providers", "too_many") in found


# --- features that do not exist with Keycloak --------------------------------------------


def test_multi_tenancy_is_rejected() -> None:
    assert ("auth.multi_tenant", "unsupported_value") in codes(
        issues_for(with_auth(multi_tenant=True))
    )


def test_tenant_row_rule_is_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["permissions"] = [
            {"entity": "Item", "operation": "list", "roles": ["member"], "row_rule": "tenant"}
        ]

    assert ("auth.permissions[0].row_rule", "unsupported_value") in codes(issues_for(mutate))


def test_custom_registration_fields_are_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["registration"]["custom_fields"] = [
            {"name": "company", "label": "Company", "type": "string"}
        ]

    assert ("auth.registration.custom_fields", "unsupported_value") in codes(issues_for(mutate))


def test_sms_otp_is_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["password_reset"] = {"email_magic_link": False, "sms_otp": True}

    assert ("auth.password_reset.sms_otp", "unsupported_value") in codes(issues_for(mutate))


def test_self_assignable_and_invite_only_roles_are_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["roles"][1]["self_assignable"] = True
        d["auth"]["roles"][0]["invite_only"] = True

    found = codes(issues_for(mutate))
    assert ("auth.roles[1].self_assignable", "unsupported_value") in found
    assert ("auth.roles[0].invite_only", "unsupported_value") in found


def test_invite_only_registration_needs_nothing_else() -> None:
    # In Keycloak it only turns self-registration off; no smtp, admin role or app_url needed.
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["registration"] = {"invite_only": True, "email_verification_required": False}
        d["auth"]["roles"] = [{"name": "member", "label": "Member"}]

    assert issues_for(mutate) == []


def test_email_verification_needs_smtp_but_not_an_app_url() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["registration"] = {"email_verification_required": True}

    assert ("auth.smtp", "required") in codes(issues_for(mutate))

    def with_smtp(d: dict[str, Any]) -> None:
        mutate(d)
        d["auth"]["smtp"] = {
            "host": "smtp.example.com",
            "port": 587,
            "use_tls": True,
            "from_email": "noreply@example.com",
            "from_name": "Shop",
        }

    assert issues_for(with_smtp) == []


# --- shared rules still apply ------------------------------------------------------------


def test_role_rules_still_apply() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["roles"].append({"name": "x", "label": "X", "inherits_from": "missing"})

    assert ("auth.roles[2].inherits_from", "unknown_reference") in codes(issues_for(mutate))


def test_permission_rules_still_apply() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["roles"] = [{"name": "member", "label": "Member"}]
        d["auth"]["permissions"] = [
            {"entity": "Item", "operation": "list", "roles": ["member"], "row_rule": "role_scoped"}
        ]

    assert ("auth.permissions[0].row_rule", "unknown_reference") in codes(issues_for(mutate))


def test_entities_cannot_shadow_the_keycloak_tables() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = "auth_provider_lock"

    assert any(i.code == "duplicate_name" for i in issues_for(mutate))

    # auth_tenants is free here: tenancy does not exist with Keycloak.
    def free(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = "auth_tenants"

    assert issues_for(free) == []
