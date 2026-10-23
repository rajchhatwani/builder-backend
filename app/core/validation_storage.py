"""Validation rules for the `storage` block of a spec, and for `file` fields.

Kept apart from validation.py (which imports this module) and therefore free of its types: issues
are reported through the `add(path, code, message)` callable it passes in.
"""

import re
from collections.abc import Callable

from app.core.enums import DownloadMode, StorageBackend
from app.core.spec_models import Spec, SpecEntity, SpecStorage

Add = Callable[[str, str, str], None]

# Tables the generated storage module creates; entities may not use these names.
STORAGE_TABLES = ("stor_audit_log", "stor_files")

# Floors and ceilings for the security knobs: an unsafe value is rejected, never clamped.
AUDIT_RETENTION_DAYS = (365, 36_500)
RESCAN_AFTER_DAYS = (1, 365)
SCAN_TIMEOUT_SECONDS = (5, 600)
MAX_FILE_MB = (1, 1024)
UPLOADS_PER_HOUR = (1, 10_000)
MAX_QUOTA_MB = 10_000_000
MAX_ALLOWED_TYPES = 50

# Dots are refused in bucket names: they break TLS certificate matching for virtual-hosted URLs.
_BUCKET_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")
_REGION_RE = re.compile(r"[a-z]{2}(?:-[a-z]+)+-[0-9]{1,2}")
_PREFIX_RE = re.compile(r"[a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)*")
_TOKEN = r"[a-z0-9][a-z0-9!#$&^_.+-]{0,62}"
_MIME_RE = re.compile(rf"{_TOKEN}/(?:{_TOKEN}|\*)")
_ROLE_FIELDS = ("upload", "share", "read", "read_all", "delete", "delete_all", "operate")


def storage_active(spec: Spec) -> bool:
    return spec.storage is not None and spec.storage.enabled


def file_field_names(entity: SpecEntity) -> list[str]:
    return [f.name for f in entity.fields if f.type == "file"]


def check_storage(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    storage = spec.storage
    if storage is None or not storage.enabled:
        _check_file_fields_need_storage(spec, add)
        if storage is not None:
            _check_enums(storage, add)  # work in progress still gets its shapes checked
        return
    _check_enums(storage, add)
    auth = spec.auth
    if auth is None or not auth.enabled:
        add("storage", "requires_auth", "file storage needs authentication: turn auth on first")
    for i, entity in enumerate(spec.entities):
        if entity.plural_path == "files":
            add(
                f"entities[{i}].plural_path",
                "reserved_word",
                "'files' is the route of the storage module",
            )
    _check_bucket(storage, add)
    _check_limits(storage, add)
    _check_types(storage, add)
    _check_security(storage, add)
    _check_roles(storage, spec, add)
    _check_file_fields(spec, entities, add)


def _check_enums(storage: SpecStorage, add: Add) -> None:
    for path, value, enum in (
        ("storage.backend", storage.backend, StorageBackend),
        ("storage.download_mode", storage.download_mode, DownloadMode),
    ):
        allowed = [e.value for e in enum]
        if value not in allowed:
            add(path, "invalid_value", f"must be one of {', '.join(allowed)}")


def _in(value: int, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= value <= bounds[1]


def _check_bucket(storage: SpecStorage, add: Add) -> None:
    bucket = storage.bucket
    if not _BUCKET_RE.fullmatch(bucket) or "--" in bucket or re.fullmatch(r"[0-9-]+", bucket):
        add(
            "storage.bucket",
            "invalid_value",
            "3-63 characters: lower-case letters, digits and hyphens, starting and ending with a "
            "letter or digit, not made of digits only",
        )
    elif bucket.startswith(("xn--", "sthree-")) or bucket.endswith(("-s3alias", "--ol-s3")):
        add("storage.bucket", "invalid_value", "this prefix or suffix is reserved by S3")
    region = storage.region
    if storage.backend == StorageBackend.s3 and not region:
        add("storage.region", "required", "name the AWS region of the bucket (e.g. eu-west-1)")
    if region is not None and not _REGION_RE.fullmatch(region):
        add("storage.region", "invalid_value", "looks like us-east-1 or eu-central-2")
    prefix = storage.key_prefix
    if len(prefix) > 100 or not _PREFIX_RE.fullmatch(prefix):
        add(
            "storage.key_prefix",
            "invalid_value",
            "lower-case letters, digits and hyphens, with / between parts, at most 100 characters; "
            "the credentials you create should be allowed to touch only this prefix",
        )


def _check_limits(storage: SpecStorage, add: Add) -> None:
    if not _in(storage.max_file_mb, MAX_FILE_MB):
        add(
            "storage.max_file_mb",
            "out_of_range",
            f"must be between {MAX_FILE_MB[0]} and {MAX_FILE_MB[1]}",
        )
    quota = storage.user_quota_mb
    if quota is not None and not storage.max_file_mb <= quota <= MAX_QUOTA_MB:
        add(
            "storage.user_quota_mb",
            "out_of_range",
            f"must be between max_file_mb and {MAX_QUOTA_MB}",
        )
    if not _in(storage.uploads_per_hour, UPLOADS_PER_HOUR):
        add(
            "storage.uploads_per_hour",
            "out_of_range",
            f"must be between {UPLOADS_PER_HOUR[0]} and {UPLOADS_PER_HOUR[1]}",
        )


def _check_types(storage: SpecStorage, add: Add) -> None:
    types = storage.allowed_types
    if len(types) > MAX_ALLOWED_TYPES:
        add("storage.allowed_types", "too_many", f"at most {MAX_ALLOWED_TYPES} entries")
    if len(set(types)) != len(types):
        add("storage.allowed_types", "duplicate_name", "each type may be listed once")
    for i, value in enumerate(types):
        path = f"storage.allowed_types[{i}]"
        if value == "*/*":
            add(path, "invalid_value", "leave the list empty to allow every type")
        elif not _MIME_RE.fullmatch(value) or len(value) > 100:
            add(path, "invalid_value", "must look like image/png or image/*")


def _check_security(storage: SpecStorage, add: Add) -> None:
    sec = storage.security
    for name, value, bounds in (
        ("audit_retention_days", sec.audit_retention_days, AUDIT_RETENTION_DAYS),
        ("rescan_after_days", sec.rescan_after_days, RESCAN_AFTER_DAYS),
        ("scan_timeout_seconds", sec.scan_timeout_seconds, SCAN_TIMEOUT_SECONDS),
    ):
        if not _in(value, bounds):
            add(
                f"storage.security.{name}",
                "out_of_range",
                f"must be between {bounds[0]} and {bounds[1]}",
            )


def _check_roles(storage: SpecStorage, spec: Spec, add: Add) -> None:
    role_names = {r.name for r in spec.auth.roles} if spec.auth is not None else set()
    for name in _ROLE_FIELDS:
        roles: list[str] = getattr(storage.roles, name)
        path = f"storage.roles.{name}"
        if len(set(roles)) != len(roles):
            add(path, "duplicate_name", "each role may be listed once")
        for role in roles:
            if role not in role_names:
                add(path, "unknown_reference", f"role {role[:40]!r} does not exist")
    for name in ("upload", "read", "operate"):
        if not getattr(storage.roles, name):
            add(
                f"storage.roles.{name}",
                "required",
                "list at least one role (an empty list means nobody may do it)",
            )
    if not storage.roles.delete and not storage.roles.delete_all:
        add(
            "storage.roles.delete",
            "required",
            "someone must be able to delete files (erasure requests, mistakes): list a role under "
            "delete or delete_all",
        )


def _check_file_fields_need_storage(spec: Spec, add: Add) -> None:
    for i, entity in enumerate(spec.entities):
        for j, field in enumerate(entity.fields):
            if field.type == "file":
                add(
                    f"entities[{i}].fields[{j}].type",
                    "storage_required",
                    "file fields need file storage: turn storage on first",
                )


def _check_file_fields(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    """A file field attaches a file to a row. Whoever writes the row must be signed in, because the
    attach check compares the file's owner and tenant with the caller's."""
    by_entity: dict[str, dict[str, list[str]]] = {}
    if spec.auth is not None:
        for perm in spec.auth.permissions:
            by_entity.setdefault(perm.entity, {})[perm.operation] = list(perm.roles)
    for i, entity in enumerate(spec.entities):
        if not file_field_names(entity) or entities.get(entity.name) is not entity:
            continue
        ops = set(entity.options.operations)
        for op in ("create", "replace", "update"):
            if op in ops and not by_entity.get(entity.name, {}).get(op):
                add(
                    f"entities[{i}].fields",
                    "file_field_public_write",
                    f"{entity.name}.{op} has no role restriction: a file can only be attached by a "
                    "signed-in user, so give this operation at least one role",
                )
