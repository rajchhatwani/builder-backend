"""Validation rules for the `storage` block of a spec and for `file` fields. Pure Python."""

import copy
from typing import Any

import pytest

from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, validate

WRITE_OPS = ("create", "replace", "update", "delete")
READ_OPS = ("list", "get", "head")


def base_spec(**storage_overrides: Any) -> dict[str, Any]:
    storage: dict[str, Any] = {
        "enabled": True,
        "backend": "s3",
        "bucket": "team-uploads",
        "region": "eu-west-1",
        "key_prefix": "uploads",
        "allowed_types": [],
        "max_file_mb": 25,
        "roles": {
            "upload": ["member"],
            "read": ["member"],
            "delete": ["member"],
            "operate": ["admin"],
        },
    }
    storage.update(storage_overrides)
    permissions = [
        {"entity": "Photo", "operation": op, "roles": ["member", "admin"]}
        for op in (*READ_OPS, *WRITE_OPS)
    ]
    return {
        "project": {"name": "Gallery", "slug": "gallery"},
        "entities": [
            {
                "name": "Photo",
                "table_name": "photos",
                "plural_path": "photos",
                "fields": [
                    {"name": "title", "type": "string", "required": True},
                    {"name": "image_id", "type": "file", "required": True},
                ],
            }
        ],
        "relations": [],
        "auth": {
            "enabled": True,
            "registration": {"email_verification_required": False},
            "password_reset": {"email_magic_link": False},
            "roles": [
                {"name": "admin", "label": "Admin"},
                {"name": "member", "label": "Member", "is_default": True},
            ],
            "permissions": permissions,
        },
        "storage": storage,
    }


def issues(raw: dict[str, Any]) -> list[ValidationIssue]:
    return validate(Spec.model_validate(raw))


def codes(raw: dict[str, Any]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in issues(raw)}


def test_a_sound_spec_has_no_issues() -> None:
    assert issues(base_spec()) == []


def test_storage_needs_auth() -> None:
    raw = base_spec()
    raw["auth"]["enabled"] = False
    assert ("storage", "requires_auth") in codes(raw)


def test_a_disabled_block_is_only_checked_for_shape() -> None:
    raw = base_spec(enabled=False, bucket="", backend="floppy")
    found = codes(raw)
    assert ("storage.backend", "invalid_value") in found
    assert ("storage.bucket", "invalid_value") not in found  # work in progress


def test_file_fields_need_storage_switched_on() -> None:
    raw = base_spec(enabled=False)
    assert any(code == "storage_required" for _path, code in codes(raw))
    raw["storage"] = None
    assert any(code == "storage_required" for _path, code in codes(raw))


@pytest.mark.parametrize(
    "bucket",
    [
        "",
        "ab",
        "UPPER-case",
        "has_underscore",
        "has.dot",
        "-leading",
        "trailing-",
        "12345",
        "a--b",
        "xn--thing",
        "x" * 64,
        "ends-s3alias",
        "sthree-thing",
    ],
)
def test_bad_bucket_names(bucket: str) -> None:
    assert ("storage.bucket", "invalid_value") in codes(base_spec(bucket=bucket))


@pytest.mark.parametrize("bucket", ["abc", "team-uploads", "a1b", "x" * 63])
def test_good_bucket_names(bucket: str) -> None:
    assert not any(path == "storage.bucket" for path, _ in codes(base_spec(bucket=bucket)))


def test_s3_needs_a_region_and_minio_does_not() -> None:
    assert ("storage.region", "required") in codes(base_spec(region=None))
    assert ("storage.region", "invalid_value") in codes(base_spec(region="Europe"))
    assert not any(
        path == "storage.region" for path, _ in codes(base_spec(backend="minio", region=None))
    )


@pytest.mark.parametrize(
    "prefix", ["", "/leading", "trailing/", "double//slash", "UPPER", "a b", "../up", "x" * 101]
)
def test_bad_prefixes(prefix: str) -> None:
    assert ("storage.key_prefix", "invalid_value") in codes(base_spec(key_prefix=prefix))


@pytest.mark.parametrize("prefix", ["uploads", "teams/files", "a-b/c-d/e"])
def test_good_prefixes(prefix: str) -> None:
    assert not any(path == "storage.key_prefix" for path, _ in codes(base_spec(key_prefix=prefix)))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_file_mb", 0),
        ("max_file_mb", 1025),
        ("uploads_per_hour", 0),
        ("uploads_per_hour", 10_001),
        ("user_quota_mb", 5),  # below max_file_mb (25): a single file would not fit
    ],
)
def test_limits_are_bounded(field: str, value: int) -> None:
    assert (f"storage.{field}", "out_of_range") in codes(base_spec(**{field: value}))


def test_allowed_types() -> None:
    assert issues(base_spec(allowed_types=["image/png", "image/*", "application/pdf"])) == []
    for bad in (
        ["*/*"],
        ["png"],
        ["image/"],
        ["IMAGE/PNG"],
        ["image/png", "image/png"],
        ["text/plain; charset=x"],
    ):
        assert any(
            path.startswith("storage.allowed_types")
            for path, _ in codes(base_spec(allowed_types=bad))
        ), bad
    too_many = [f"application/x-type{i}" for i in range(51)]
    assert ("storage.allowed_types", "too_many") in codes(base_spec(allowed_types=too_many))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("audit_retention_days", 364),
        ("audit_retention_days", 36_501),
        ("rescan_after_days", 0),
        ("rescan_after_days", 366),
        ("scan_timeout_seconds", 4),
        ("scan_timeout_seconds", 601),
    ],
)
def test_security_knobs_have_floors_and_ceilings(name: str, value: int) -> None:
    assert (f"storage.security.{name}", "out_of_range") in codes(base_spec(security={name: value}))


def test_the_audit_retention_floor_is_one_year() -> None:
    assert issues(base_spec(security={"audit_retention_days": 365})) == []


def test_enums() -> None:
    assert ("storage.download_mode", "invalid_value") in codes(base_spec(download_mode="teleport"))


def test_roles_must_exist_and_the_essential_ones_must_not_be_empty() -> None:
    found = codes(base_spec(roles={"upload": ["ghost"], "read": [], "delete": [], "operate": []}))
    assert ("storage.roles.upload", "unknown_reference") in found
    assert ("storage.roles.read", "required") in found
    assert ("storage.roles.operate", "required") in found
    assert ("storage.roles.delete", "required") in found  # erasure must be possible
    assert ("storage.roles.upload", "duplicate_name") in codes(
        base_spec(
            roles={
                "upload": ["member", "member"],
                "read": ["member"],
                "delete_all": ["admin"],
                "operate": ["admin"],
            }
        )
    )


def test_erasure_can_be_given_by_either_delete_role() -> None:
    raw = base_spec(
        roles={
            "upload": ["member"],
            "read": ["member"],
            "delete_all": ["admin"],
            "operate": ["admin"],
        }
    )
    assert issues(raw) == []


def test_files_is_a_reserved_route() -> None:
    raw = base_spec()
    raw["entities"][0]["plural_path"] = "files"
    assert ("entities[0].plural_path", "reserved_word") in codes(raw)


def test_the_storage_tables_are_reserved() -> None:
    raw = base_spec()
    raw["entities"][0]["table_name"] = "stor_files"
    assert any(code == "duplicate_name" for _path, code in codes(raw))


# --- file fields ---------------------------------------------------------------------------------


def test_file_fields_cannot_be_unique_or_have_defaults_or_bounds() -> None:
    for option, value in (
        ("unique", True),
        ("default", "x"),
        ("max_length", 5),
        ("min_value", 1),
        ("enum_values", ["a"]),
    ):
        raw = base_spec()
        raw["entities"][0]["fields"][1][option] = value
        assert any(path.startswith("entities[0].fields[1]") for path, _ in codes(raw)), option


def test_file_fields_cannot_be_filtered_or_sorted() -> None:
    for option in ("filterable", "sortable"):
        raw = base_spec()
        raw["entities"][0]["options"] = {option: ["image_id"]}
        assert any(code == "incompatible_type" for _path, code in codes(raw)), option


@pytest.mark.parametrize("op", ["create", "replace", "update"])
def test_writing_a_file_field_needs_a_signed_in_user(op: str) -> None:
    raw = base_spec()
    raw["auth"]["permissions"] = [
        p
        for p in raw["auth"]["permissions"]
        if not (p["entity"] == "Photo" and p["operation"] == op)
    ]
    assert ("entities[0].fields", "file_field_public_write") in codes(raw)


def test_a_file_field_on_an_entity_without_write_operations_is_fine() -> None:
    raw = base_spec()
    raw["entities"][0]["options"] = {"operations": ["list", "get"]}
    raw["auth"]["permissions"] = [
        p for p in raw["auth"]["permissions"] if p["operation"] in ("list", "get")
    ]
    assert issues(raw) == []


def test_round_trip_through_the_model_keeps_the_block() -> None:
    spec = Spec.model_validate(base_spec(allowed_types=["image/*"], user_quota_mb=100))
    again = Spec.model_validate(copy.deepcopy(spec.model_dump(mode="json")))
    assert again.storage == spec.storage
    assert again.storage is not None and again.storage.allowed_types == ["image/*"]
