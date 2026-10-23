"""Validation rules for the spec's `auth` block. Pure Python: no DB, no HTTP."""

from collections.abc import Callable
from typing import Any

import pytest

from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, validate


def auth_spec(**overrides: Any) -> dict[str, Any]:
    """A minimal valid spec with email auth configured."""
    auth: dict[str, Any] = {
        "enabled": True,
        "app_url": "https://app.example.com",
        "smtp": {
            "host": "smtp.example.com",
            "port": 587,
            "use_tls": True,
            "from_email": "noreply@example.com",
            "from_name": "Example",
        },
    }
    auth.update(overrides)
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
    data = auth_spec()
    if mutate is not None:
        mutate(data)
    return validate(Spec.model_validate(data))


def codes(issues: list[ValidationIssue]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in issues}


def with_auth(**changes: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"].update(changes)

    return mutate


def test_minimal_email_auth_is_valid() -> None:
    assert issues_for() == []


def test_disabled_auth_is_not_validated() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"] = {"enabled": False, "jwt_algorithm": "RS256", "token_store": "redis"}

    assert issues_for(mutate) == []


# --- tokens and limits ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_token_ttl_minutes", 0),
        ("access_token_ttl_minutes", 1441),
        ("refresh_token_ttl_days", 0),
        ("refresh_token_ttl_days", 366),
    ],
)
def test_token_lifetimes_are_bounded(field: str, value: int) -> None:
    assert (f"auth.{field}", "out_of_range") in codes(issues_for(with_auth(**{field: value})))


def test_otp_ttl_is_bounded() -> None:
    found = codes(issues_for(with_auth(password_reset={"otp_ttl_minutes": 61})))
    assert ("auth.password_reset.otp_ttl_minutes", "out_of_range") in found


@pytest.mark.parametrize(
    "bad", ["", "5", "five/minute", "5/fortnight", "5/minute; drop", "-1/hour"]
)
def test_rate_limits_must_match_the_grammar(bad: str) -> None:
    assert ("auth.login_rate_limit", "invalid_value") in codes(
        issues_for(with_auth(login_rate_limit=bad))
    )


@pytest.mark.parametrize("good", ["5/minute", "10/hour", "5/15minutes", "100/day", "1/second"])
def test_valid_rate_limits_pass(good: str) -> None:
    assert issues_for(with_auth(reset_rate_limit=good)) == []


def test_deletion_mode_must_be_known() -> None:
    assert ("auth.deletion_mode", "invalid_value") in codes(
        issues_for(with_auth(deletion_mode="shred"))
    )


# --- options the generator cannot build yet ---------------------------------------------


def test_redis_token_store_is_supported() -> None:
    assert issues_for(with_auth(token_store="redis")) == []


def test_unknown_token_store_is_invalid() -> None:
    assert ("auth.token_store", "invalid_value") in codes(
        issues_for(with_auth(token_store="memcached"))
    )


def test_rs256_is_supported() -> None:
    assert issues_for(with_auth(jwt_algorithm="RS256")) == []


def test_unknown_jwt_algorithm_is_invalid() -> None:
    assert ("auth.jwt_algorithm", "invalid_value") in codes(
        issues_for(with_auth(jwt_algorithm="none"))
    )


# --- multi-tenancy ----------------------------------------------------------------------

TENANT_ROLES = [
    {"name": "admin", "label": "Admin"},
    {"name": "member", "label": "Member", "is_default": True},
]


def tenant_auth(**changes: Any) -> Callable[[dict[str, Any]], None]:
    return with_auth(multi_tenant=True, roles=TENANT_ROLES, **changes)


def test_multi_tenancy_is_valid_with_an_admin_role_email_and_app_url() -> None:
    assert issues_for(tenant_auth()) == []


def test_multi_tenancy_needs_an_admin_role() -> None:
    roles = [{"name": "member", "label": "Member"}]
    found = codes(issues_for(with_auth(multi_tenant=True, roles=roles)))
    assert ("auth.multi_tenant", "unknown_reference") in found


def test_multi_tenancy_needs_email_for_invitations() -> None:
    def mutate(d: dict[str, Any]) -> None:
        tenant_auth()(d)
        d["auth"].pop("smtp")
        d["auth"].pop("app_url")
        d["auth"]["password_reset"] = {"email_magic_link": False}
        d["auth"]["registration"] = {"email_verification_required": False}

    assert ("auth.multi_tenant", "required") in codes(issues_for(mutate))


def test_multi_tenancy_cannot_be_combined_with_invite_only_sign_up() -> None:
    found = codes(
        issues_for(
            tenant_auth(registration={"invite_only": True, "email_verification_required": True})
        )
    )
    assert ("auth.multi_tenant", "invalid_value") in found


# --- invitations and role flags ---------------------------------------------------------

INVITE_ROLES = [
    {"name": "admin", "label": "Admin"},
    {"name": "member", "label": "Member", "is_default": True},
]


def invite_only(**auth: Any) -> Callable[[dict[str, Any]], None]:
    return with_auth(
        roles=auth.pop("roles", INVITE_ROLES),
        registration={"invite_only": True, "email_verification_required": True},
        **auth,
    )


def test_invite_only_registration_is_valid_with_an_admin_and_email() -> None:
    assert issues_for(invite_only()) == []


def test_invite_only_needs_smtp_app_url_and_an_admin() -> None:
    def mutate(d: dict[str, Any]) -> None:
        invite_only(roles=[{"name": "member", "label": "Member"}])(d)
        d["auth"].pop("smtp")
        d["auth"].pop("app_url")
        d["auth"]["password_reset"] = {"email_magic_link": False}
        d["auth"]["registration"] = {"invite_only": True, "email_verification_required": False}

    found = codes(issues_for(mutate))
    assert ("auth.registration.invite_only", "required") in found
    assert ("auth.registration.invite_only", "unknown_reference") in found


def test_an_invite_only_role_turns_invitations_on() -> None:
    roles = [*INVITE_ROLES, {"name": "vip", "label": "VIP", "invite_only": True}]
    assert issues_for(with_auth(roles=roles)) == []

    def no_admin(d: dict[str, Any]) -> None:
        with_auth(roles=[{"name": "vip", "label": "VIP", "invite_only": True}])(d)

    assert ("auth.roles", "unknown_reference") in codes(issues_for(no_admin))


@pytest.mark.parametrize("flag", ["is_default", "self_assignable"])
def test_an_invite_only_role_cannot_also_be_open(flag: str) -> None:
    roles = [*INVITE_ROLES, {"name": "vip", "label": "VIP", "invite_only": True, flag: True}]
    assert ("auth.roles[2]", "invalid_value") in codes(issues_for(with_auth(roles=roles)))


def test_the_tenant_row_rule_needs_multi_tenancy() -> None:
    roles = [{"name": "admin", "label": "Admin"}]
    permission = {"entity": "Item", "operation": "list", "roles": ["admin"], "row_rule": "tenant"}
    assert ("auth.permissions[0].row_rule", "invalid_value") in codes(
        issues_for(with_auth(roles=roles, permissions=[permission]))
    )


def test_the_tenant_row_rule_is_valid_with_multi_tenancy() -> None:
    permission = {"entity": "Item", "operation": "list", "roles": ["member"], "row_rule": "tenant"}
    assert issues_for(tenant_auth(permissions=[permission])) == []


@pytest.mark.parametrize(
    ("rule", "column"),
    [("tenant", "tenant_id"), ("owner", "created_by_id"), ("role_scoped", "created_by_id")],
)
def test_row_rules_cannot_clash_with_the_columns_they_add(rule: str, column: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        tenant_auth(
            permissions=[
                {"entity": "Item", "operation": "list", "roles": ["member"], "row_rule": rule}
            ]
        )(d)
        d["entities"][0]["fields"].append({"name": column, "type": "string", "max_length": 10})

    assert ("auth.permissions[0].entity", "reserved_name") in codes(issues_for(mutate))


# --- permissions and row rules ----------------------------------------------------------

ADMIN = [{"name": "admin", "label": "Admin"}, {"name": "member", "label": "Member"}]


def with_permission(**perm: Any) -> Callable[[dict[str, Any]], None]:
    entry = {"entity": "Item", "operation": "list", "roles": ["admin"], **perm}
    return with_auth(roles=ADMIN, permissions=[entry])


@pytest.mark.parametrize(
    "perm",
    [
        {},
        {"roles": []},
        {"roles": ["admin", "member"], "row_rule": "owner"},
        {"row_rule": "role_scoped"},
        {"operation": "create", "roles": ["member"]},
    ],
)
def test_valid_permissions_pass(perm: dict[str, Any]) -> None:
    assert issues_for(with_permission(**perm)) == []


def test_role_scoped_needs_an_admin_role() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["roles"] = [{"name": "member", "label": "Member"}]
        d["auth"]["permissions"] = [
            {"entity": "Item", "operation": "list", "roles": ["member"], "row_rule": "role_scoped"}
        ]

    assert ("auth.permissions[0].row_rule", "unknown_reference") in codes(issues_for(mutate))


def test_owner_rule_limits_the_table_name_length() -> None:
    def mutate(d: dict[str, Any]) -> None:
        with_permission(row_rule="owner")(d)
        d["entities"][0]["table_name"] = "t" * 36

    assert ("auth.permissions[0].entity", "identifier_too_long") in codes(issues_for(mutate))


def filter_spec(field: dict[str, Any], **perm: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"].append(field)
        with_permission(row_rule="custom_filter", custom_filter_field=field["name"], **perm)(d)

    return mutate


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ({"name": "status", "type": "enum", "enum_values": ["draft", "live"]}, "live"),
        ({"name": "kind", "type": "string", "max_length": 20}, "news"),
        ({"name": "rank", "type": "integer"}, "7"),
        ({"name": "hidden", "type": "boolean"}, "false"),
    ],
)
def test_custom_filters_on_simple_fields_pass(field: dict[str, Any], value: str) -> None:
    assert issues_for(filter_spec(field, custom_filter_value=value)) == []


@pytest.mark.parametrize(
    ("field", "value", "path", "code"),
    [
        (
            {"name": "status", "type": "enum", "enum_values": ["a"]},
            "b",
            "custom_filter_value",
            "invalid_value",
        ),
        ({"name": "rank", "type": "integer"}, "seven", "custom_filter_value", "invalid_value"),
        ({"name": "hidden", "type": "boolean"}, "yes", "custom_filter_value", "invalid_value"),
        (
            {"name": "born", "type": "date"},
            "2000-01-01",
            "custom_filter_field",
            "unsupported_value",
        ),
        ({"name": "score", "type": "float"}, "1.5", "custom_filter_field", "unsupported_value"),
    ],
)
def test_custom_filters_are_type_checked(
    field: dict[str, Any], value: str, path: str, code: str
) -> None:
    found = codes(issues_for(filter_spec(field, custom_filter_value=value)))
    assert (f"auth.permissions[0].{path}", code) in found


def test_custom_filter_on_a_missing_field() -> None:
    def mutate(d: dict[str, Any]) -> None:
        with_permission(
            row_rule="custom_filter", custom_filter_field="ghost", custom_filter_value="x"
        )(d)

    assert ("auth.permissions[0].custom_filter_field", "unknown_field") in codes(issues_for(mutate))


# --- SMTP -------------------------------------------------------------------------------


def test_smtp_is_required_for_email_flows() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"].pop("smtp")

    assert ("auth.smtp", "required") in codes(issues_for(mutate))


def test_smtp_is_optional_when_no_email_flow_is_enabled() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"].pop("smtp")
        d["auth"]["password_reset"] = {"email_magic_link": False}
        d["auth"]["registration"] = {"email_verification_required": False}

    assert issues_for(mutate) == []


@pytest.mark.parametrize("host", ["", "bad host", "smtp.example.com\r\nBcc: x", 'a"; import os'])
def test_smtp_host_is_validated(host: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["smtp"]["host"] = host

    assert ("auth.smtp.host", "invalid_value") in codes(issues_for(mutate))


@pytest.mark.parametrize(
    "sender", ["nope", "a@b", "a b@c.com", "x@y.com\nBcc: z@y.com", '"a"@b.com']
)
def test_smtp_from_email_is_validated(sender: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["smtp"]["from_email"] = sender

    assert ("auth.smtp.from_email", "invalid_value") in codes(issues_for(mutate))


def test_smtp_from_name_must_be_single_line() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["smtp"]["from_name"] = "Evil\r\nBcc: x@y.com"

    assert ("auth.smtp.from_name", "invalid_value") in codes(issues_for(mutate))


def test_smtp_port_range() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["smtp"]["port"] = 70000

    assert ("auth.smtp.port", "out_of_range") in codes(issues_for(mutate))


# --- SMS --------------------------------------------------------------------------------


def sms_auth(
    provider: str | None = "twilio", sender: str = "+14155550123"
) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["password_reset"] = {"sms_otp": True}
        d["auth"]["sms_provider"] = provider
        d["auth"]["sms"] = {"from_number": sender}

    return mutate


def test_sms_otp_with_twilio_is_valid() -> None:
    assert issues_for(sms_auth()) == []


def test_sms_otp_requires_provider_and_config() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["password_reset"] = {"sms_otp": True}

    found = codes(issues_for(mutate))
    assert ("auth.sms_provider", "required") in found
    assert ("auth.sms", "required") in found


def test_unknown_sms_provider_is_invalid() -> None:
    assert ("auth.sms_provider", "invalid_value") in codes(issues_for(sms_auth("carrier_pigeon")))


@pytest.mark.parametrize(
    "sender", ["4155550123", "+0123456", "+1 415 555 0123", "+1415555012345678"]
)
def test_sms_from_number_must_be_e164(sender: str) -> None:
    assert ("auth.sms.from_number", "invalid_value") in codes(
        issues_for(sms_auth("vonage", sender))
    )


def test_sns_accepts_an_alphanumeric_sender_id() -> None:
    assert issues_for(sms_auth("aws_sns", "MyApp")) == []


def test_sns_rejects_an_overlong_sender_id() -> None:
    assert ("auth.sms.from_number", "invalid_value") in codes(
        issues_for(sms_auth("aws_sns", "MyAppNameTooLong"))
    )


# --- branding ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["ftp://x.com", "javascript:alert(1)", 'https://a.com/"x', "app.example.com"]
)
def test_app_url_must_be_http(url: str) -> None:
    assert ("auth.app_url", "invalid_value") in codes(issues_for(with_auth(app_url=url)))


def test_app_url_is_required_for_links() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"].pop("app_url")

    assert ("auth.app_url", "required") in codes(issues_for(mutate))


def test_app_name_must_be_single_line() -> None:
    assert ("auth.app_name", "invalid_value") in codes(issues_for(with_auth(app_name="a\nb")))


# --- roles ------------------------------------------------------------------------------


def role(name: str, **kw: Any) -> dict[str, Any]:
    return {"name": name, "label": name.title(), **kw}


def test_roles_are_valid() -> None:
    roles = [role("admin"), role("editor", inherits_from="admin"), role("member", is_default=True)]
    assert issues_for(with_auth(roles=roles)) == []


def test_role_names_are_snake_case_identifiers() -> None:
    found = codes(issues_for(with_auth(roles=[role('Admin"; drop')])))
    assert ("auth.roles[0].name", "invalid_identifier") in found


def test_duplicate_roles_are_rejected() -> None:
    found = codes(issues_for(with_auth(roles=[role("admin"), role("admin")])))
    assert ("auth.roles[1].name", "duplicate_name") in found


def test_inherits_from_must_exist() -> None:
    found = codes(issues_for(with_auth(roles=[role("editor", inherits_from="ghost")])))
    assert ("auth.roles[0].inherits_from", "unknown_reference") in found


def test_role_inheritance_cycles_are_rejected() -> None:
    roles = [role("a", inherits_from="b"), role("b", inherits_from="a")]
    assert ("auth.roles[0].inherits_from", "cycle") in codes(issues_for(with_auth(roles=roles)))


def test_role_cannot_inherit_from_itself() -> None:
    roles = [role("a", inherits_from="a")]
    assert ("auth.roles[0].inherits_from", "cycle") in codes(issues_for(with_auth(roles=roles)))


# --- custom registration fields ---------------------------------------------------------


def custom(name: str, type_: str = "string", **kw: Any) -> dict[str, Any]:
    return {"name": name, "label": name.title(), "type": type_, **kw}


def with_fields(*fields: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["registration"] = {
            "email_verification_required": True,
            "custom_fields": list(fields),
        }

    return mutate


def test_custom_fields_are_valid() -> None:
    fields = [
        custom("full_name", max_length=80),
        custom("age", "integer", min_value=0, max_value=150),
        custom("plan", "enum", enum_values=["free", "pro"], default_value="free"),
        custom("newsletter", "boolean", default_value="false"),
    ]
    assert issues_for(with_fields(*fields)) == []


@pytest.mark.parametrize("name", ["email", "phone", "password_hash", "roles", "id", "created_at"])
def test_custom_field_cannot_reuse_a_builtin_column(name: str) -> None:
    found = codes(issues_for(with_fields(custom(name))))
    assert ("auth.registration.custom_fields[0].name", "reserved_name") in found


@pytest.mark.parametrize("name", ["class", "order", "Bad-Name", 'x"; import os'])
def test_custom_field_names_are_identifier_checked(name: str) -> None:
    found = codes(issues_for(with_fields(custom(name))))
    assert any(path == "auth.registration.custom_fields[0].name" for path, _ in found)


def test_duplicate_custom_fields_are_rejected() -> None:
    found = codes(issues_for(with_fields(custom("nick"), custom("nick"))))
    assert ("auth.registration.custom_fields[1].name", "duplicate_name") in found


def test_unknown_custom_field_type() -> None:
    found = codes(issues_for(with_fields(custom("x", "blob"))))
    assert ("auth.registration.custom_fields[0].type", "invalid_value") in found


def test_enum_custom_field_needs_values() -> None:
    found = codes(issues_for(with_fields(custom("plan", "enum"))))
    assert ("auth.registration.custom_fields[0].enum_values", "required") in found


def test_enum_values_on_a_non_enum_field() -> None:
    found = codes(issues_for(with_fields(custom("nick", enum_values=["a"]))))
    assert ("auth.registration.custom_fields[0].enum_values", "not_applicable") in found


def test_length_and_value_bounds_must_fit_the_type() -> None:
    found = codes(
        issues_for(
            with_fields(
                custom("age", "integer", max_length=3),
                custom("nick", min_value=1),
            )
        )
    )
    assert ("auth.registration.custom_fields[0].max_length", "not_applicable") in found
    assert ("auth.registration.custom_fields[1].min_value", "not_applicable") in found


def test_bound_ranges_must_be_ordered() -> None:
    found = codes(
        issues_for(
            with_fields(
                custom("nick", min_length=10, max_length=5),
                custom("age", "integer", min_value=9, max_value=1),
            )
        )
    )
    assert ("auth.registration.custom_fields[0].min_length", "invalid_range") in found
    assert ("auth.registration.custom_fields[1].min_value", "invalid_range") in found


@pytest.mark.parametrize(
    ("type_", "default"),
    [
        ("integer", "abc"),
        ("float", "nan"),
        ("boolean", "yes"),
        ("date", "tomorrow"),
        ("datetime", "noon"),
    ],
)
def test_defaults_must_parse_for_their_type(type_: str, default: str) -> None:
    found = codes(issues_for(with_fields(custom("x", type_, default_value=default))))
    assert ("auth.registration.custom_fields[0].default_value", "invalid_default") in found


def test_enum_default_must_be_a_listed_value() -> None:
    found = codes(
        issues_for(with_fields(custom("plan", "enum", enum_values=["a"], default_value="b")))
    )
    assert ("auth.registration.custom_fields[0].default_value", "invalid_default") in found


# --- table collisions -------------------------------------------------------------------


@pytest.mark.parametrize("table", ["auth_users", "auth_refresh_tokens", "auth_verification_codes"])
def test_entities_cannot_use_auth_tables(table: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = table

    assert ("entities[0].table_name", "duplicate_name") in codes(issues_for(mutate))


def test_auth_tables_are_free_when_auth_is_disabled() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"]["enabled"] = False
        d["entities"][0]["table_name"] = "auth_users"

    assert issues_for(mutate) == []


# --- structure that is checked even when auth is switched off ---------------------------


def test_bad_enum_values_are_reported_even_when_disabled() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"] = {
            "enabled": False,
            "token_store": "memcached",
            "jwt_algorithm": "none",
            "deletion_mode": "shred",
            "sms_provider": "carrier_pigeon",
            "registration": {"custom_fields": [{"name": "x", "label": "X", "type": "blob"}]},
        }

    assert codes(issues_for(mutate)) == {
        ("auth.token_store", "invalid_value"),
        ("auth.jwt_algorithm", "invalid_value"),
        ("auth.deletion_mode", "invalid_value"),
        ("auth.sms_provider", "invalid_value"),
        ("auth.registration.custom_fields[0].type", "invalid_value"),
    }


def test_invalid_enum_is_reported_once_when_enabled() -> None:
    found = [
        i for i in issues_for(with_auth(token_store="memcached")) if i.path == "auth.token_store"
    ]
    assert [i.code for i in found] == ["invalid_value"]


def permission(**kw: Any) -> dict[str, Any]:
    return {"entity": "Item", "operation": "list", "roles": ["admin"], **kw}


def disabled_with(**auth: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        d["auth"] = {"enabled": False, "roles": [{"name": "admin", "label": "Admin"}], **auth}

    return mutate


def test_valid_permissions_pass_structural_checks_when_disabled() -> None:
    assert issues_for(disabled_with(permissions=[permission()])) == []


@pytest.mark.parametrize(
    ("change", "path", "code"),
    [
        ({"entity": "Ghost"}, "auth.permissions[0].entity", "unknown_entity"),
        ({"operation": "everything"}, "auth.permissions[0].operation", "invalid_value"),
        ({"roles": ["ghost"]}, "auth.permissions[0].roles", "unknown_reference"),
        ({"row_rule": "everyone"}, "auth.permissions[0].row_rule", "invalid_value"),
        ({"row_rule": "custom_filter"}, "auth.permissions[0]", "required"),
        ({"custom_filter_field": "status"}, "auth.permissions[0]", "not_applicable"),
    ],
)
def test_permission_references_are_checked(change: dict[str, Any], path: str, code: str) -> None:
    found = codes(issues_for(disabled_with(permissions=[permission(**change)])))
    assert (path, code) in found


def test_duplicate_permission_slots_are_rejected() -> None:
    found = codes(issues_for(disabled_with(permissions=[permission(), permission(roles=[])])))
    assert ("auth.permissions[1]", "duplicate_name") in found
