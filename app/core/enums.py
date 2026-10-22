from enum import StrEnum


class DbEngine(StrEnum):
    postgres = "postgres"


class FieldType(StrEnum):
    string = "string"
    text = "text"
    integer = "integer"
    bigint = "bigint"
    float = "float"
    decimal = "decimal"
    boolean = "boolean"
    date = "date"
    datetime = "datetime"
    uuid = "uuid"
    json = "json"
    enum = "enum"


class RelationKind(StrEnum):
    one_to_many = "one_to_many"
    many_to_many = "many_to_many"
    one_to_one = "one_to_one"


class OnDelete(StrEnum):
    cascade = "cascade"
    set_null = "set_null"
    restrict = "restrict"


# ── Phase 2: Auth ─────────────────────────────────────────────────────────────


class AuthCustomFieldType(StrEnum):
    """Field types available for custom registration fields on generated projects."""

    string = "string"
    text = "text"
    integer = "integer"
    float = "float"
    boolean = "boolean"
    date = "date"
    datetime = "datetime"
    email = "email"
    phone = "phone"
    url = "url"
    enum = "enum"


class TokenStore(StrEnum):
    """Backend used to persist refresh tokens in generated projects."""

    db = "db"
    redis = "redis"


class SmsProvider(StrEnum):
    """Third-party SMS gateway for OTP delivery."""

    twilio = "twilio"
    aws_sns = "aws_sns"
    vonage = "vonage"


class JwtAlgorithm(StrEnum):
    """Signing algorithm for access tokens in generated projects."""

    hs256 = "HS256"
    rs256 = "RS256"


class DeletionMode(StrEnum):
    """How user records are removed in generated projects."""

    soft = "soft"  # is_active = false; row kept
    hard = "hard"  # row physically deleted


class RowRule(StrEnum):
    """Row-level access rule applied by the generator to entity CRUD queries."""

    owner = "owner"               # WHERE created_by = current_user.id
    role_scoped = "role_scoped"   # admins see all; others see own rows
    tenant = "tenant"             # WHERE tenant_id = current_user.tenant_id
    custom_filter = "custom_filter"  # configurable field + value filter


class AuthOperation(StrEnum):
    """Entity operations that can have RBAC permissions attached.

    `replace` shadows `str.replace`; the type: ignore is required because mypy's
    str-inheritance check flags it as an incompatible assignment even though
    the enum semantics are correct.
    """

    list_op = "list"
    get = "get"
    create = "create"
    replace = "replace"  # type: ignore[assignment]  # shadows str.replace
    update = "update"
    delete = "delete"
    head = "head"
