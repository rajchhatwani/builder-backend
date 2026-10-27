"""SCIM 2.0 wire format (RFC 7643 / 7644): filters, PATCH operations, payload parsing.

Covers the shapes the four big IdPs send (§12.E.6): Okta (no-path `replace` with a value object),
Entra ID (capitalised ops, `"False"` strings, `emails[type eq "work"].value` paths, `members`
add/remove), JumpCloud and Google Workspace (PUT-style full bodies).
"""

import pytest

from app.services import scim_protocol as p
from app.services.scim_protocol import ScimError

# -- filters --------------------------------------------------------------------------------


def test_filter_eq_user_name() -> None:
    f = p.parse_filter('userName eq "Alice@Acme.test"', p.USER_FILTER_ATTRS)
    assert f == p.Filter("username", "Alice@Acme.test")


def test_filter_attribute_names_are_case_insensitive_and_external_id_works() -> None:
    assert p.parse_filter('EXTERNALID eq "00u1"', p.USER_FILTER_ATTRS).attr == "externalid"
    assert p.parse_filter('emails.value eq "a@b.test"', p.USER_FILTER_ATTRS).attr == "emails.value"
    assert (
        p.parse_filter('emails[type eq "work"].value eq "a@b.test"', p.USER_FILTER_ATTRS).attr
        == "emails.value"
    )
    assert p.parse_filter('displayName eq "Owners"', p.GROUP_FILTER_ATTRS).attr == "displayname"


def test_filter_value_with_escaped_quote() -> None:
    f = p.parse_filter(r'displayName eq "Team \"A\""', p.GROUP_FILTER_ATTRS)
    assert f.value == 'Team "A"'


@pytest.mark.parametrize(
    "text",
    [
        'userName co "a"',  # only eq is supported
        'userName eq "a" and active eq true',
        "userName eq a",  # value must be quoted
        'title eq "x"',  # not a filterable attribute
        "",
    ],
)
def test_unsupported_filters_are_invalid_filter(text: str) -> None:
    with pytest.raises(ScimError) as exc:
        p.parse_filter(text, p.USER_FILTER_ATTRS)
    assert exc.value.status == 400
    assert exc.value.scim_type == "invalidFilter"


# -- booleans (Entra sends strings) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"), [(True, True), (False, False), ("True", True), ("false", False)]
)
def test_as_bool(raw: object, expected: bool) -> None:
    assert p.as_bool(raw, "active") is expected


def test_as_bool_refuses_other_values() -> None:
    with pytest.raises(ScimError) as exc:
        p.as_bool("yes", "active")
    assert exc.value.scim_type == "invalidValue"


# -- user payloads --------------------------------------------------------------------------

OKTA_USER = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
    "userName": "alice@acme.test",
    "name": {"givenName": "Alice", "familyName": "Smith"},
    "emails": [{"primary": True, "value": "alice@acme.test", "type": "work"}],
    "displayName": "Alice Smith",
    "locale": "en-US",
    "externalId": "00u1abcd",
    "groups": [],
    "password": "ignored-Secret-1",
    "active": True,
}


def test_parse_okta_user() -> None:
    u = p.parse_user(OKTA_USER)
    assert u.user_name == "alice@acme.test"
    assert u.email == "alice@acme.test"
    assert u.external_id == "00u1abcd"
    assert (u.given_name, u.family_name, u.display_name) == ("Alice", "Smith", "Alice Smith")
    assert u.active is True


def test_user_name_without_at_uses_the_primary_work_email() -> None:
    body = {
        "userName": "asmith",
        "emails": [
            {"value": "home@example.test", "type": "home"},
            {"value": "Alice@Acme.test", "type": "work", "primary": True},
        ],
    }
    u = p.parse_user(body)
    assert u.user_name == "asmith"
    assert u.email == "alice@acme.test"


def test_user_defaults_active_and_needs_an_email() -> None:
    assert p.parse_user({"userName": "bob@acme.test"}).active is True
    with pytest.raises(ScimError) as exc:
        p.parse_user({"userName": "bob"})
    assert exc.value.scim_type == "invalidValue"
    with pytest.raises(ScimError):
        p.parse_user({"emails": [{"value": "x@acme.test"}]})  # userName is required


def test_user_name_is_capped() -> None:
    with pytest.raises(ScimError):
        p.parse_user({"userName": "a" * 250 + "@acme.test"})


# -- user PATCH -----------------------------------------------------------------------------


def _current() -> dict[str, object]:
    return p.user_patch_base(
        user_name="alice@acme.test",
        external_id="00u1",
        given_name="Alice",
        family_name="Smith",
        display_name="Alice Smith",
        email="alice@acme.test",
        active=True,
    )


def _ops(*ops: dict[str, object]) -> dict[str, object]:
    return {"schemas": [p.PATCH_OP_SCHEMA], "Operations": list(ops)}


def test_okta_deactivate_is_a_no_path_replace() -> None:
    out = p.parse_user(
        p.apply_user_patch(_current(), _ops({"op": "replace", "value": {"active": False}}))
    )
    assert out.active is False
    assert out.user_name == "alice@acme.test"


def test_entra_capitalised_op_string_bool_and_paths() -> None:
    out = p.parse_user(
        p.apply_user_patch(
            _current(),
            _ops(
                {"op": "Replace", "path": "active", "value": "False"},
                {"op": "Replace", "path": "name.givenName", "value": "Alicia"},
                {"op": "Add", "path": 'emails[type eq "work"].value', "value": "alicia@acme.test"},
                {"op": "Replace", "path": "displayName", "value": "Alicia Smith"},
                {
                    "op": "Add",
                    "path": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:department",
                    "value": "Sales",
                },
            ),
        )
    )
    assert out.active is False
    assert out.given_name == "Alicia"
    assert out.email == "alice@acme.test"  # an e-mail-shaped userName names the account
    assert out.display_name == "Alicia Smith"


def test_work_email_patch_changes_the_account_email_when_user_name_is_not_one() -> None:
    base = {**_current(), "userName": "asmith"}
    out = p.parse_user(
        p.apply_user_patch(
            base,
            _ops({"op": "replace", "path": 'emails[type eq "work"].value', "value": "A@Acme.test"}),
        )
    )
    assert out.email == "a@acme.test"


def test_no_path_value_with_dotted_keys() -> None:
    out = p.parse_user(
        p.apply_user_patch(
            _current(),
            _ops({"op": "replace", "value": {"name.familyName": "Jones", "active": True}}),
        )
    )
    assert out.family_name == "Jones"


def test_remove_external_id() -> None:
    out = p.parse_user(p.apply_user_patch(_current(), _ops({"op": "remove", "path": "externalId"})))
    assert out.external_id is None


@pytest.mark.parametrize(
    "body",
    [
        {"Operations": [{"op": "move", "path": "active", "value": True}]},
        {"Operations": "nope"},
        {"Operations": [{"op": "replace", "path": "id", "value": "x"}]},  # id is read-only
        {},
    ],
)
def test_bad_patches_are_400(body: dict[str, object]) -> None:
    with pytest.raises(ScimError) as exc:
        p.apply_user_patch(_current(), body)
    assert exc.value.status == 400


# -- groups ---------------------------------------------------------------------------------


def test_parse_group() -> None:
    g = p.parse_group({"displayName": "Owners", "externalId": "g1", "members": [{"value": "u1"}]})
    assert (g.display_name, g.external_id, g.member_ids) == ("Owners", "g1", ["u1"])
    with pytest.raises(ScimError):
        p.parse_group({"members": []})


def test_group_patch_entra_add_and_remove_members() -> None:
    gp = p.parse_group_patch(
        _ops(
            {"op": "Add", "path": "members", "value": [{"value": "u1"}, {"value": "u2"}]},
            {"op": "Remove", "path": "members", "value": [{"value": "u3"}]},
        )
    )
    assert gp.add == ["u1", "u2"] and gp.remove == ["u3"] and gp.replace is None


def test_group_patch_okta_remove_by_filter_and_rename() -> None:
    gp = p.parse_group_patch(
        _ops(
            {"op": "remove", "path": 'members[value eq "u9"]'},
            {"op": "replace", "value": {"id": "ignored", "displayName": "Admins"}},
        )
    )
    assert gp.remove == ["u9"]
    assert gp.display_name == "Admins"


def test_group_patch_replace_members_and_remove_all() -> None:
    assert p.parse_group_patch(
        _ops({"op": "replace", "path": "members", "value": [{"value": "u1"}]})
    ).replace == ["u1"]
    assert p.parse_group_patch(_ops({"op": "remove", "path": "members"})).replace == []


# -- responses ------------------------------------------------------------------------------


def test_error_body_shape() -> None:
    body = ScimError(409, "already exists", "uniqueness").body()
    assert body == {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "status": "409",
        "scimType": "uniqueness",
        "detail": "already exists",
    }


def test_list_response_paging() -> None:
    body = p.list_response([{"id": "a"}], total=3, start_index=2)
    assert body["totalResults"] == 3
    assert body["startIndex"] == 2
    assert body["itemsPerPage"] == 1
    assert body["Resources"] == [{"id": "a"}]


def test_paging_parameters_are_clamped() -> None:
    assert p.paging(None, None) == (1, p.DEFAULT_PAGE)
    assert p.paging("0", "-5") == (1, 0)
    assert p.paging("3", "100000") == (3, p.MAX_PAGE)
    with pytest.raises(ScimError):
        p.paging("x", None)


def test_discovery_documents() -> None:
    spc = p.service_provider_config("https://api.test/scim/v2")
    assert spc["patch"] == {"supported": True}
    assert spc["filter"]["supported"] is True
    assert spc["authenticationSchemes"][0]["type"] == "oauthbearertoken"
    types = p.resource_types("https://api.test/scim/v2")
    assert {t["id"] for t in types} == {"User", "Group"}
    schemas = p.schemas()
    assert {s["id"] for s in schemas} == {p.USER_SCHEMA, p.GROUP_SCHEMA}
