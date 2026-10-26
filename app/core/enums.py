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
    file = "file"  # reference to an uploaded file (needs the storage feature)


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

    owner = "owner"  # WHERE created_by = current_user.id
    role_scoped = "role_scoped"  # admins see all; others see own rows
    tenant = "tenant"  # WHERE tenant_id = current_user.tenant_id
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


class AuthProvider(StrEnum):
    """Where a generated project's users and tokens come from."""

    builtin = "builtin"
    keycloak = "keycloak"


class KeycloakMode(StrEnum):
    """own: the project ships its own Keycloak. shared: it trusts an existing realm."""

    own = "own"
    shared = "shared"


class MfaMode(StrEnum):
    off = "off"
    optional = "optional"
    required = "required"


class IdpType(StrEnum):
    """Kinds of external login a Keycloak realm can offer."""

    google = "google"
    microsoft = "microsoft"
    github = "github"
    oidc = "oidc"


class PaymentProvider(StrEnum):
    """Payment service providers the generated payments module can talk to."""

    stripe = "stripe"
    razorpay = "razorpay"


class PaymentsProfile(StrEnum):
    """Starting point for the sizing numbers; any number the user sets wins."""

    small = "small"
    medium = "medium"
    large = "large"


class PaymentsAvailability(StrEnum):
    """single: one of everything is acceptable. ha: no single process may be a point of failure."""

    single = "single"
    ha = "ha"


class WebhookMode(StrEnum):
    """inline: a webhook is processed inside the request. queued: stored and handed to workers."""

    inline = "inline"
    queued = "queued"


class StorageBackend(StrEnum):
    """Where uploaded files live. Both speak the S3 API; minio is any self-hosted compatible server."""

    s3 = "s3"
    minio = "minio"


class DownloadMode(StrEnum):
    """proxy: the API streams the file. presigned: the API redirects to a short-lived signed URL."""

    proxy = "proxy"
    presigned = "presigned"


# ── Platform accounts (the builder's own users, not generated projects') ─────────────────


class PlatformRole(StrEnum):
    """What a person may do on the platform itself, independent of any project."""

    customer = "customer"
    platform_support = "platform_support"  # admin console, read-only
    platform_admin = "platform_admin"  # admin console, full


class AccountStatus(StrEnum):
    active = "active"
    suspended = "suspended"


class MemberRole(StrEnum):
    """A person's role inside one project. Ordered: viewer < editor < owner."""

    viewer = "viewer"
    editor = "editor"
    owner = "owner"


class OrgKind(StrEnum):
    """Shape of an organization: a one-member account versus a multi-member team."""

    personal = "personal"
    team = "team"


class OrgRole(StrEnum):
    """A person's role inside one organization. Ordered: member < admin < owner."""

    member = "member"
    admin = "admin"
    owner = "owner"


class SubscriptionStatus(StrEnum):
    """One Subscription row per org; status mirrors Stripe but Stripe is not required."""

    trial = "trial"
    active = "active"
    past_due = "past_due"
    canceled = "canceled"


class InvitationStatus(StrEnum):
    """Transient status of an Organization invitation. The row keeps timestamps too."""

    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"
    expired = "expired"


class TokenAudience(StrEnum):
    """Which surface a refresh token / access token belongs to. They are never interchangeable."""

    app = "app"
    admin = "admin"


class AuditResult(StrEnum):
    ok = "ok"
    denied = "denied"
    error = "error"


class AuthorizationModel(StrEnum):
    """How a generated project decides who may do what.

    rbac  roles and per-operation permissions with row rules (the original model)
    abac  attribute-based: policies over subject, resource and environment attributes, all
          applying to every signed-in person (NIST SP 800-162)
    pbac  policy-based: named policies attached to roles; allow and deny effects. PBAC has no
          standard definition: this is the meaning used here, and the docs say so
    """

    rbac = "rbac"
    abac = "abac"
    pbac = "pbac"
