"""The SPEC: the contract between the builder API and the generator (PLAN.md section 3).

Deliberately lenient about *values* (plain `str` for names and enum-like fields, no
patterns or length limits). Rejecting bad values is `validation.validate`'s job, so one
call can report every issue instead of stopping at the first Pydantic error. Structure
is strict (`extra="forbid"`, correct JSON types) so nothing is silently dropped on import.

Relations reference entities by *name*, not id, so a spec is portable between projects.
Field order is the list order (no `position`); entities and relations are emitted sorted
so the same model always serializes to the same spec.
"""

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SPEC_VERSION = 1
ALLOWED_OPERATIONS = frozenset({"list", "get", "create", "replace", "update", "delete", "head"})


class _SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpecProject(_SpecModel):
    name: str
    slug: str
    description: str | None = None
    db_engine: str = "postgres"


class SpecEntityOptions(_SpecModel):
    operations: list[str] = Field(default_factory=lambda: sorted(ALLOWED_OPERATIONS))
    filterable: list[str] = Field(default_factory=list)
    sortable: list[str] = Field(default_factory=list)
    searchable: list[str] = Field(default_factory=list)
    default_page_size: int = 20
    max_page_size: int = 100
    soft_delete: bool = False


class SpecField(_SpecModel):
    name: str
    type: str
    required: bool = False
    unique: bool = False
    indexed: bool = False
    default: Any | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    enum_values: list[str] | None = None


class SpecEntity(_SpecModel):
    name: str
    table_name: str
    plural_path: str
    options: SpecEntityOptions = Field(default_factory=SpecEntityOptions)
    fields: list[SpecField] = Field(default_factory=list)


class SpecRelation(_SpecModel):
    kind: str
    from_entity: str
    to_entity: str
    from_name: str
    to_name: str
    on_delete: str = "restrict"
    required: bool = False


class SpecSmtpConfig(_SpecModel):
    host: str
    port: int = 587
    use_tls: bool = True
    from_email: str
    from_name: str


class SpecSmsConfig(_SpecModel):
    from_number: str


class SpecAuthCustomField(_SpecModel):
    name: str
    label: str
    type: str  # AuthCustomFieldType value; validation module checks legality
    required: bool = False
    unique: bool = False
    indexed: bool = False
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    default_value: str | None = None
    enum_values: list[str] | None = None


class SpecRole(_SpecModel):
    name: str
    label: str
    is_default: bool = False
    self_assignable: bool = False
    invite_only: bool = False
    inherits_from: str | None = None


class SpecPermission(_SpecModel):
    entity: str  # entity name (not id) for portability
    operation: str  # AuthOperation value; validation module checks legality
    roles: list[str] = Field(default_factory=list)
    row_rule: str | None = None  # RowRule value or None
    custom_filter_field: str | None = None
    custom_filter_value: str | None = None


class SpecPasswordReset(_SpecModel):
    email_magic_link: bool = True
    sms_otp: bool = False
    otp_ttl_minutes: int = 10


class SpecRegistration(_SpecModel):
    email_verification_required: bool = True
    invite_only: bool = False
    custom_fields: list[SpecAuthCustomField] = Field(default_factory=list)


class SpecAuthSecrets(_SpecModel):
    """Decrypted credentials injected at generation time.

    This model is NEVER serialised in HTTP responses.  It is populated
    by the generation service after calling AuthSecretsService.get_for_generator()
    and exists solely so Jinja templates can reference credentials by name.
    """

    smtp_username: str | None = None
    smtp_password: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    vonage_api_key: str | None = None
    vonage_api_secret: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str | None = None


class SpecIdentityProvider(_SpecModel):
    """One external login offered by the Keycloak realm. The client secret is never part of
    the spec: the generated project reads it from KC_IDP_<ALIAS>_CLIENT_SECRET."""

    alias: str
    type: str  # IdpType value; validation module checks legality
    display_name: str | None = None
    client_id: str
    tenant_id: str | None = None  # microsoft only: the Entra tenant (a GUID)
    hosted_domain: str | None = None  # google only: restrict sign-in to one Workspace domain
    # oidc only: the provider's endpoints, as listed in its .well-known/openid-configuration
    issuer: str | None = None
    authorization_url: str | None = None
    token_url: str | None = None
    jwks_url: str | None = None
    userinfo_url: str | None = None  # optional


class SpecKeycloak(_SpecModel):
    mode: str = "own"  # KeycloakMode value
    realm: str
    api_client_id: str
    web_client_id: str
    redirect_uris: list[str] = Field(default_factory=list)
    password_min_length: int = 12
    mfa: str = "optional"  # MfaMode value
    session_idle_minutes: int = 30
    session_max_hours: int = 10
    audit_retention_days: int = 90
    identity_providers: list[SpecIdentityProvider] = Field(default_factory=list)


class SpecSuiteRef(_SpecModel):
    """Reserved: this app is one of several that share a sign-in hub. Empty (None on SpecAuth)
    for every project that has not opted in; the generator ignores it for now."""

    suite_id: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9-]*$")
    hub_issuer: str | None = Field(default=None, max_length=512)
    join_state: str = "none"  # none | planned | joined


class SpecAuth(_SpecModel):
    enabled: bool = True
    # Who manages users and tokens. The keycloak block is kept while the provider is builtin,
    # so switching back and forth does not lose the settings.
    provider: str = "builtin"  # AuthProvider value
    keycloak: SpecKeycloak | None = None
    token_store: str = "db"  # TokenStore value
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    jwt_algorithm: str = "HS256"  # JwtAlgorithm value
    deletion_mode: str = "soft"  # DeletionMode value
    multi_tenant: bool = False
    security_headers_enabled: bool = True
    app_name: str | None = None
    app_url: str | None = None
    password_reset: SpecPasswordReset = Field(default_factory=SpecPasswordReset)
    registration: SpecRegistration = Field(default_factory=SpecRegistration)
    smtp: SpecSmtpConfig | None = None
    sms_provider: str | None = None  # SmsProvider value
    sms: SpecSmsConfig | None = None
    login_rate_limit: str = "5/15minutes"
    register_rate_limit: str = "10/hour"
    reset_rate_limit: str = "3/hour"
    roles: list[SpecRole] = Field(default_factory=list)
    permissions: list[SpecPermission] = Field(default_factory=list)
    suite: SpecSuiteRef | None = None
    # Populated at generation time only — excluded from JSON output
    secrets: SpecAuthSecrets = Field(default_factory=SpecAuthSecrets, exclude=True)


class SpecPolicy(_SpecModel):
    """One authorization policy (abac / pbac). `when` is plain data, never code: see authz_engine."""

    id: str
    description: str = ""
    effect: str  # "allow" | "deny"
    actions: list[str]  # "Order.list", "Order.*" or "*"
    when: dict[str, Any] | None = None


class SpecAuthorization(_SpecModel):
    model: str = "rbac"  # AuthorizationModel value
    policies: list[SpecPolicy] = Field(default_factory=list)
    # pbac only: "*" (everyone signed in) or a role name -> ids of the policies it carries
    attachments: dict[str, list[str]] = Field(default_factory=dict)


class SpecObservability(_SpecModel):
    """OpenTelemetry in the generated service: traces and metrics over OTLP/HTTP, log correlation.

    Everything an operator tunes in production (endpoint, sampler, service name) stays an
    environment variable of the generated project; this block only sets the defaults and what is
    generated. No endpoint or header (they may hold credentials) is ever stored here.
    """

    enabled: bool = True
    service_name: str | None = None  # default: the project slug
    sample_ratio: float = 0.1  # share of new traces that are recorded, 0..1
    metrics: bool = True
    db_spans: bool = True  # one span per SQL statement (statement text only, never values)
    exclude_paths: list[str] = Field(default_factory=lambda: ["/health", "/ready"])
    extra_redact_keys: list[str] = Field(default_factory=list)  # added to the built-in secret keys
    local_stack: bool = True  # emit deploy/observability/ (collector, Jaeger, Prometheus)
    expected_rps: int | None = None  # peak requests per second: only used for sizing advice


class SpecDeployEnvironment(_SpecModel):
    """One environment (dev, staging, prod ...). `profile` fills every number left empty."""

    name: str
    profile: str = "small"  # small | medium | large
    min_instances: int | None = None
    max_instances: int | None = None
    cpu: int | None = None  # millicores; must be a size the cloud offers
    memory: int | None = None  # MB
    db_storage_gb: int | None = None
    db_high_availability: bool | None = None  # default: on above the small profile
    deletion_protection: bool | None = None  # default: on for "prod"


def _default_environments() -> list[SpecDeployEnvironment]:
    return [
        SpecDeployEnvironment(name="dev", profile="small"),
        SpecDeployEnvironment(name="staging", profile="small"),
        SpecDeployEnvironment(name="prod", profile="medium"),
    ]


class SpecDeployment(_SpecModel):
    """CI/CD workflows and Terraform for one cloud. No cloud credential is ever stored: pipelines
    sign in with short-lived OIDC tokens (one-time trust setup: deploy/<cloud>/bootstrap)."""

    enabled: bool = True
    cloud: str = "aws"  # aws | azure | gcp
    region: str = ""
    github_repo: str = ""  # owner/name, trusted by the cloud's OIDC setup
    environments: list[SpecDeployEnvironment] = Field(default_factory=_default_environments)


class SpecDocTemplate(_SpecModel):
    """One PDF template: the plain-data structure `doc_engine` renders, plus who may render it."""

    id: str  # the route key: POST /documents/{id}/render
    title: str = ""
    kind: str = "custom"  # the library template it was copied from, or custom
    entity: str | None = None  # bind to an entity: POST /documents/{id}/records/{record_id}
    compute: str | None = None  # the list whose totals are recomputed (items)
    roles: list[str] = Field(default_factory=list)  # who may render it; empty means nobody
    template: dict[str, Any] = Field(default_factory=dict)


class SpecDocuments(_SpecModel):
    """PDF documents (invoice, receipt, statement ...) rendered by the generated API."""

    enabled: bool = True
    templates: list[SpecDocTemplate] = Field(default_factory=list)
    rate_limit: str = "30/minute"  # per client, on every document route


class SpecPaymentsPayable(_SpecModel):
    """The entity a payment is for (e.g. Order): where the amount, currency and status live."""

    entity: str
    amount_field: str  # a decimal field: the amount in major units (19.99)
    currency: str | None = None  # a fixed ISO 4217 code ...
    currency_field: str | None = None  # ... or a string field on the entity holding one
    status_field: str  # an enum field the payments module moves between the values below
    status_pending: str
    status_paid: str
    status_partially_refunded: str
    status_refunded: str


class SpecPaymentsRoles(_SpecModel):
    """Who may do what. An empty list means nobody (fail closed), unlike entity permissions."""

    create: list[str] = Field(default_factory=list)  # start a payment for a payable row
    read: list[str] = Field(default_factory=list)  # read the payments they started
    read_all: list[str] = Field(default_factory=list)  # read every payment of the tenant
    refund: list[str] = Field(default_factory=list)
    approve_refund: list[str] = Field(default_factory=list)  # second person above the threshold
    operate: list[str] = Field(default_factory=list)  # dead jobs, reconcile, audit log


class SpecPaymentsScale(_SpecModel):
    """Expected load. `payments_sizing.size()` turns it into replicas, pools and worker counts;
    any explicit override below wins over the computed number."""

    profile: str = "small"  # PaymentsProfile value: fills the numbers left empty
    peak_payments_per_minute: int | None = None
    peak_webhooks_per_minute: int | None = None  # default: 5x payments
    db_max_connections: int = 100
    availability: str = "single"  # PaymentsAvailability value
    pgbouncer: bool = False
    kubernetes: bool = False  # also emit deploy/k8s/
    webhook_mode: str | None = None  # WebhookMode value; None = chosen from the load
    api_replicas: int | None = None
    server_workers: int | None = None
    worker_replicas: int | None = None
    worker_concurrency: int | None = None
    pool_size: int | None = None
    webhook_events_retention_days: int = 90
    jobs_retention_days: int = 30


class SpecPaymentsSecurity(_SpecModel):
    """Security knobs. Every one has a floor or ceiling that validation enforces."""

    webhook_tolerance_seconds: int = 300
    webhook_max_body_bytes: int = 262144
    webhook_ip_allowlist_enabled: bool = False  # the CIDRs themselves come from the environment
    idempotency_ttl_hours: int = 48
    audit_retention_days: int = 2555
    secrets_from_files: bool = True  # also read NAME_FILE variables (Docker / Kubernetes secrets)
    # Accept that the people who pay can also create or edit the item they pay for (and so set
    # its price). Off by default: validation refuses such a setup.
    allow_payer_edits: bool = False


class SpecPayments(_SpecModel):
    """Card payments through a hosted checkout. Provider secrets are never part of the spec:
    the generated project reads them from its environment."""

    enabled: bool = True
    provider: str = "stripe"  # PaymentProvider value
    payable: SpecPaymentsPayable | None = None
    currencies: list[str] = Field(default_factory=list)  # ISO 4217 allowlist
    max_amount_minor: int = 10_000_000  # largest single payment, in minor units
    success_urls: list[str] = Field(default_factory=list)
    cancel_urls: list[str] = Field(default_factory=list)
    roles: SpecPaymentsRoles = Field(default_factory=SpecPaymentsRoles)
    refund_approval_threshold_minor: int | None = None  # refunds above this need a 2nd person
    scale: SpecPaymentsScale = Field(default_factory=SpecPaymentsScale)
    security: SpecPaymentsSecurity = Field(default_factory=SpecPaymentsSecurity)


class SpecStorageRoles(_SpecModel):
    """Who may do what with files. An empty list means nobody (fail closed)."""

    upload: list[str] = Field(default_factory=list)
    share: list[str] = Field(default_factory=list)  # may mark a file as readable by every reader
    read: list[str] = Field(default_factory=list)  # download their own files and shared ones
    read_all: list[str] = Field(default_factory=list)  # download every file of the tenant
    delete: list[str] = Field(default_factory=list)  # delete their own files
    delete_all: list[str] = Field(default_factory=list)  # delete any file of the tenant
    operate: list[str] = Field(default_factory=list)  # audit log, quarantine, scanner status


class SpecStorageSecurity(_SpecModel):
    """Security knobs. Every one has a floor or ceiling that validation enforces."""

    audit_retention_days: int = 2555
    audit_ip: bool = True  # record the caller's IP address in the audit log (personal data)
    rescan_after_days: int = 30  # `maintenance --rescan` rescans files scanned longer ago than this
    scan_timeout_seconds: int = 120


class SpecStorage(_SpecModel):
    """File uploads into an S3-compatible bucket, scanned for malware before they are stored.
    Bucket credentials are never part of the spec: the generated project reads them from its
    environment."""

    enabled: bool = True
    backend: str = "s3"  # StorageBackend value
    bucket: str = ""
    region: str | None = None
    key_prefix: str = "uploads"
    allowed_types: list[str] = Field(default_factory=list)  # empty = any type
    max_file_mb: int = 25
    user_quota_mb: int | None = None
    uploads_per_hour: int = 60
    download_mode: str = "proxy"  # DownloadMode value
    allow_inline_images: bool = False
    roles: SpecStorageRoles = Field(default_factory=SpecStorageRoles)
    security: SpecStorageSecurity = Field(default_factory=SpecStorageSecurity)


class SpecTransition(_SpecModel):
    """One allowed move of a state machine: from any of `from_states` to `to_state`.

    `when` is an expression (app/core/expr) over the record's own fields: the move is refused
    unless it is true (null counts as false). `roles` limits who may trigger it. With NO roles
    the move is open to anyone who may UPDATE the entity (default deny): the caller must pass the same
    update access as PATCH / PUT (roles, row rules or policies), so a read-only role cannot move a
    record. To let a role move records without edit rights, list that role here. `auto` moves are applied by the platform right after a write
    whenever their guard holds, so they never have `roles`."""

    name: str
    from_states: list[str] = Field(default_factory=list)
    to_state: str
    when: str | None = None
    roles: list[str] = Field(default_factory=list)
    auto: bool = False


class SpecStateMachine(_SpecModel):
    """A lifecycle for one entity. The states are the `enum_values` of `field`, which must be a
    required enum field; callers cannot write it directly, only move it through transitions."""

    entity: str
    field: str
    initial: str
    transitions: list[SpecTransition] = Field(default_factory=list)


class SpecSetting(_SpecModel):
    """A typed value the running service reads and a role may change at run time (per tenant when
    the project is multi-tenant). `default` is what everybody gets until a value is saved.
    Settings are for business knobs, never secrets: names that look like credentials are refused."""

    key: str
    type: str = "string"  # string | int | bool | decimal
    default: str | int | bool | None = None  # decimals are written as strings: "0.15"
    label: str | None = None
    description: str | None = None
    minimum: str | int | None = None  # int and decimal only
    maximum: str | int | None = None
    max_length: int | None = None  # string only (default 200)
    read_roles: list[str] = Field(default_factory=list)  # empty = any caller of the API
    edit_roles: list[str] = Field(default_factory=list)  # empty = nobody can change it at run time


class SpecSequence(_SpecModel):
    """A gapless counter: a number is consumed only when the caller's transaction commits.
    Numbers look like `<prefix>[<year>-]<zero padded counter>`."""

    name: str
    prefix: str = ""
    padding: int = 0
    start: int = 1
    per_tenant: bool = False  # one counter per tenant (needs auth.multi_tenant)
    reset_yearly: bool = False  # the counter restarts at `start` every calendar year (UTC)
    view_roles: list[str] = Field(default_factory=list)  # who may read the counters; empty = nobody
    # Numbers a field automatically: set BOTH to make the platform draw the next number into
    # `entity`.`field` on every create, in the same transaction as the insert. The field is then
    # read-only for callers (validation_numbering). Leave both empty for a counter that code draws.
    entity: str | None = None
    field: str | None = None


class SpecListItem(_SpecModel):
    value: str
    label: str
    color: str | None = None  # "#rrggbb"
    locked: bool = False  # a tenant may relabel it but never switch it off


class SpecList(_SpecModel):
    """A named list of values (statuses, categories ...). `items` is the system default set; a
    tenant (or the whole project when single-tenant) may add values, relabel, recolour, reorder and
    switch off the unlocked ones, if it holds one of `edit_roles`."""

    name: str
    label: str | None = None
    items: list[SpecListItem] = Field(default_factory=list)
    max_items: int = 100  # system + custom values per tenant
    edit_roles: list[str] = Field(default_factory=list)  # empty = nobody can change it at run time


class SpecHistory(_SpecModel):
    """Change history for one entity: every create, update and delete of the listed `fields` is
    recorded with the actor, the old value and the new value, and kept for `retention_days`.
    Only the listed fields are ever recorded. `view_roles` may read an entity's history through the
    API; empty = nobody (fail closed)."""

    entity: str
    fields: list[str] = Field(default_factory=list)
    retention_days: int
    view_roles: list[str] = Field(default_factory=list)


class SpecEvents(_SpecModel):
    """Transactional outbox and typed event bus (C10). Off unless `enabled`. Every entity gets
    created / updated / deleted events, and every state machine a `<entity>.transitioned` event; each
    is written to the outbox in the write's own transaction and delivered at least once, in order per
    record, by a relay. `adapter` is where events go: `in_process` (subscribers in the same app) or
    `redis_streams` (not implemented yet). Delivered rows are purged after `retention_days`."""

    enabled: bool = False
    adapter: str = "in_process"
    retention_days: int = 14


class SpecRateBucket(_SpecModel):
    """A token bucket: holds at most `capacity` tokens and gets `refill_per_second` back each second."""

    capacity: int
    refill_per_second: float


class SpecRateGroup(_SpecModel):
    """Limits for a group of routes (first matching group wins; `methods` empty = every method).
    `user` / `tenant` replace the defaults for this group (callers without a valid token always use
    `anonymous`); `cost` is what one request takes out."""

    name: str
    path_prefix: str
    methods: list[str] = Field(default_factory=list)
    user: SpecRateBucket | None = None
    tenant: SpecRateBucket | None = None
    cost: int = 1


class SpecRateLimits(_SpecModel):
    """Rate limits per (tenant, caller) and per tenant, stored in Postgres so they hold across processes.
    Callers without a valid token are limited per client address (`anonymous`). A store error refuses
    writes with 503; reads are refused too unless `read_fail_open`."""

    user: SpecRateBucket = SpecRateBucket(capacity=120, refill_per_second=2.0)
    tenant: SpecRateBucket | None = None
    anonymous: SpecRateBucket = SpecRateBucket(capacity=30, refill_per_second=0.5)
    groups: list[SpecRateGroup] = Field(default_factory=list)
    read_fail_open: bool = False


class SpecQuota(_SpecModel):
    """A hard cap on a named meter per tenant and period (`day` or `month`, UTC). Requests whose method
    is in `methods` (empty = all) and whose path is under `path_prefix` use `cost` of the meter."""

    meter: str
    period: str
    limit: int
    path_prefix: str = "/"
    methods: list[str] = Field(default_factory=list)
    cost: int = 1


class SpecIdempotency(_SpecModel):
    """`Idempotency-Key` on the listed methods: the same key and request replays the first response."""

    methods: list[str] = Field(default_factory=lambda: ["POST"])
    ttl_hours: int = 24
    max_response_bytes: int = 65536


class SpecApiVersion(_SpecModel):
    date: str  # YYYY-MM-DD
    note: str = ""


class SpecApiVersioning(_SpecModel):
    """Dated API versions. `default` is what a client without an `API-Version` header gets; the newest
    version's shape is the one the code produces, older ones come from transformers in
    app/hooks/api_versions.py."""

    default: str
    versions: list[SpecApiVersion]


class SpecApiEdge(_SpecModel):
    """The API edge (C14), off unless `enabled`: idempotency keys, rate limits and quotas, dated API
    versions. Each part is on when its section is present."""

    enabled: bool = False
    idempotency: SpecIdempotency | None = None
    rate_limits: SpecRateLimits | None = None
    quotas: list[SpecQuota] = Field(default_factory=list)
    versioning: SpecApiVersioning | None = None


class SpecJobRetry(_SpecModel):
    """How a failing job is tried again: up to `max_attempts` runs in all, waiting `backoff_seconds`
    (`fixed`) or `backoff_seconds` doubling each time (`exponential`, capped at an hour) between runs.
    After the last failed run the job is parked as `dead` (visible, and it can be requeued)."""

    max_attempts: int = 3
    backoff_seconds: int = 30
    backoff: str = "exponential"


class SpecJobQueue(_SpecModel):
    """Where jobs wait. Only `postgres` (the app's own database, FOR UPDATE SKIP LOCKED) is
    implemented; `redis` and `rabbitmq` are accepted by the schema and refused by validation."""

    backend: str = "postgres"


class SpecWorkerGroup(_SpecModel):
    """A set of worker processes that run jobs from the listed `queues`, `concurrency` jobs at a time
    per process. `same_server` adds a compose service to the project; `separate_server` writes a
    bundle under deploy/workers/<name>/ to run on another machine with its own DATABASE_URL."""

    name: str
    concurrency: int = 4
    queues: list[str] = Field(default_factory=lambda: ["default"])
    placement: str = "same_server"


class SpecJob(_SpecModel):
    """A kind of background job. `handler` is the name of a function you write in the custom file
    app/hooks/jobs.py (the platform generates only the registry and the stub)."""

    name: str
    queue: str = "default"
    handler: str
    retry: SpecJobRetry = Field(default_factory=SpecJobRetry)
    timeout_seconds: int = 300


class SpecJobSchedule(_SpecModel):
    """Enqueue `job` on a 5-field `cron` in `timezone`. Exactly one job per tick, however many worker
    processes run. If ticks were missed (everything was down), `missed` decides: `catch_up_one` runs
    the most recent missed tick once, `skip` drops them."""

    name: str
    job: str
    cron: str
    timezone: str = "UTC"
    enabled: bool = True
    missed: str = "catch_up_one"


class SpecJobs(_SpecModel):
    """Background jobs, schedules and worker groups (C11). Off unless `enabled`."""

    enabled: bool = False
    queue: SpecJobQueue = Field(default_factory=SpecJobQueue)
    worker_groups: list[SpecWorkerGroup] = Field(default_factory=list)
    jobs: list[SpecJob] = Field(default_factory=list)
    schedules: list[SpecJobSchedule] = Field(default_factory=list)


class SpecWorkflowRetry(_SpecModel):
    """How a failing workflow step is tried again before the workflow counts it as failed."""

    max_attempts: int = 3
    backoff_seconds: int = 5
    backoff: str = "exponential"


class SpecWorkflowStep(_SpecModel):
    """One step. `kind: hook` runs the function you write in app/hooks/workflows.py for (workflow, step);
    `kind: job` enqueues the declared background job `job` (atomically with recording the step) and counts
    as done once enqueued. `compensate` says the step has an undo function (run in reverse order when a
    later step fails or the run is cancelled); set it false only for a step that needs no undo."""

    name: str
    kind: str = "hook"
    job: str | None = None
    compensate: bool = True
    timeout_seconds: int = 60
    retry: SpecWorkflowRetry = Field(default_factory=SpecWorkflowRetry)


class SpecWorkflow(_SpecModel):
    """A durable saga: ordered `steps` run one at a time and each completed step is recorded in Postgres,
    so a crashed or restarted worker resumes after the last completed step. `on_failure`: `compensate`
    undoes completed steps in reverse order, `fail` stops and leaves them. `roles` may start, inspect and
    cancel runs (default deny: at least one is required)."""

    name: str
    steps: list[SpecWorkflowStep] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    on_failure: str = "compensate"
    timeout_seconds: int = 3600


class SpecWorkflowWorker(_SpecModel):
    """The worker process that executes runs (`python -m app.workflows.worker`)."""

    concurrency: int = 2


class SpecWorkflows(_SpecModel):
    """Durable workflows (C12), off unless `enabled`. `runtime`: `postgres` is the built-in durable
    runner; `dbos` and `temporal` are accepted by the schema and refused by validation (not_yet_implemented)."""

    enabled: bool = False
    runtime: str = "postgres"
    worker: SpecWorkflowWorker = Field(default_factory=SpecWorkflowWorker)
    workflows: list[SpecWorkflow] = Field(default_factory=list)


class SpecProviderAdapter(_SpecModel):
    """One adapter a project may use: its `kind` (email | sms | push | payments | storage | llm |
    generic), its `name` and NON-SECRET settings. Credentials are never part of the spec: each tenant
    writes its own through the generated, admin-only vault API."""

    kind: str
    name: str
    settings: dict[str, str | int | bool] = Field(default_factory=dict)


class SpecProviders(_SpecModel):
    """Provider adapter framework and per-tenant credential vault (C15). Off unless `enabled`.
    Every kind always has the in-process `emulator`; the adapters listed here are the ones a tenant
    may select by storing credentials for them. Nothing secret lives in the spec (`secret_in_spec`)."""

    enabled: bool = False
    admin_role: str = "admin"  # the only role that may write, delete or list credentials
    adapters: list[SpecProviderAdapter] = Field(default_factory=list)
    timeout_seconds: float = 10.0
    max_attempts: int = 3
    breaker_failures: int = 5  # consecutive failures that open the circuit breaker
    breaker_reset_seconds: float = 30.0  # open -> half-open probe after this long


class SpecNotificationTemplate(_SpecModel):
    """The default template of one notification type for one channel. `{{ name }}` placeholders may
    only name the type's declared `variables` (no expressions, no filters). For email, `html: true`
    makes the body HTML: every variable is HTML-escaped. `subject` is the email subject / push title."""

    channel: str
    subject: str = ""
    body: str
    html: bool = False


class SpecNotificationType(_SpecModel):
    """One kind of notification. `category`: `transactional` (always sent) or `optional` (a user can opt
    out per channel). `on_event` (e.g. `order.created`) sends it when that event is delivered by the
    outbox: `recipient_key_field` is the event-data field naming the recipient (a user id, compared with
    the preferences) and `address_fields` maps each channel to the data field holding the address."""

    name: str
    category: str = "optional"
    channels: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    templates: list[SpecNotificationTemplate] = Field(default_factory=list)
    default_enabled: bool = True  # optional types: the setting of a user who never chose
    on_event: str | None = None
    recipient_key_field: str | None = None
    address_fields: dict[str, str] = Field(default_factory=dict)


class SpecNotifications(_SpecModel):
    """Notifications over the provider adapters (C17). Off unless `enabled`. Needs `providers` and auth.
    Messages are queued as delivery-log rows and sent by a dispatcher with retries and backoff."""

    enabled: bool = False
    admin_role: str = "admin"  # edits templates and reads the delivery log
    types: list[SpecNotificationType] = Field(default_factory=list)
    max_attempts: int = 5
    backoff_seconds: int = 30
    retention_days: int = 90  # finished delivery-log rows are purged after this long


class SpecWebhookInbound(_SpecModel):
    """One incoming webhook receiver, served at POST /webhooks/in/<name>. Requests must carry a valid
    Standard Webhooks signature (raw body, HMAC-SHA256) made with a secret the admin stored for this
    endpoint; the handler is a function you write in app/hooks/webhooks.py."""

    name: str
    tolerance_seconds: int = 300
    max_body_bytes: int = 262144
    dedupe_days: int = 7


class SpecWebhooks(_SpecModel):
    """Webhooks out and in (C13). Off unless `enabled`. Needs events (the source of outgoing webhooks),
    jobs (retries with backoff: declare a job `webhook_delivery`) and providers (the vault that keeps
    the signing secrets). Nothing secret lives in the spec. Only `events` listed here can be subscribed
    to (default deny); URLs must pass the SSRF guard (public addresses only, no redirects followed)."""

    enabled: bool = False
    admin_role: str = "admin"
    events: list[str] = Field(default_factory=list)
    max_consecutive_failures: int = 5
    secret_overlap_hours: int = 24
    timeout_seconds: float = 10.0
    max_payload_bytes: int = 262144
    allow_http: bool = False
    allowed_ports: list[int] = Field(default_factory=list)
    inbound: list[SpecWebhookInbound] = Field(default_factory=list)


class SpecHookField(_SpecModel):
    """One scalar field of a hook's input or output model. The platform generates the Pydantic model
    from the list. `type` is string | int | float | decimal | bool | date | datetime | uuid."""

    name: str
    type: str = "string"
    required: bool = True


class SpecHookModel(_SpecModel):
    name: str  # class name of the generated Pydantic model
    fields: list[SpecHookField] = Field(default_factory=list)


class SpecHookBudget(_SpecModel):
    """Resource limits of one call: wall-clock milliseconds, rows read through the SDK, outbound calls."""

    cpu_ms: int = 200
    rows: int = 0
    outbound_calls: int = 0


class SpecHookEffectBudget(_SpecModel):
    """Limits of an effectful hook (H3): outbound calls per effect type in one invocation, the largest
    payload of one call in bytes, and outbound calls per minute for the hook (per API process).
    The wall-clock limit is `budget.cpu_ms`. Breaking any limit aborts the hook (its failure policy applies)."""

    calls_per_effect: int = 1
    payload_bytes: int = 10_000
    outbound_per_minute: int = 30


class SpecHookEffects(_SpecModel):
    """Per-project opt-in for effectful hooks (H2). OFF unless `enabled`. Hooks are written by TRUSTED
    authors only until the Cycle 3 sandbox exists: `trusted_authors_only` must be true to turn this on.
    `webhook_hosts` is the allow-list of hosts a hook may post to (SSRF guard still applies)."""

    enabled: bool = False
    trusted_authors_only: bool = False
    webhook_hosts: list[str] = Field(default_factory=list)


class SpecHook(_SpecModel):
    """A piece of custom logic under contract. The spec declares the name, where it runs (`point`),
    what goes in and what must come out; the platform generates the models, the stub file, the wiring
    and the gates. The body is free Python inside the marked region of the stub.

    point: `<Entity>.before_save | validate | after_save | after_commit` or
    `<Entity>.transition_guard(<manual transition>)`. kind: `pure` (no I/O) or `effect` (only at
    after_commit). failure_policy empty = the default for the point (guards and validate: fail_closed,
    effects: fail_open, other pure hooks: fail_closed). `fallback` gives the output values used by the
    `fallback` policy. `reads` lists the entities an effect hook may read through the SDK."""

    name: str
    point: str
    kind: str = "pure"
    input: SpecHookModel
    output: SpecHookModel
    failure_policy: str | None = None
    fallback: dict[str, Any] | None = None
    budget: SpecHookBudget = Field(default_factory=SpecHookBudget)
    reads: list[str] = Field(default_factory=list)
    # Effectful tier (H2/H3): refused unless `hook_effects.enabled`. `author` other than trusted is refused.
    effects: list[str] = Field(default_factory=list)  # email | sms | webhook | notification
    effect_budget: SpecHookEffectBudget | None = None
    author: str | None = None  # None / "trusted"; "ai" or "external" hooks are refused when effects are on


class SpecSeedGenerator(_SpecModel):
    """How one column of a seeded row gets its value. `type` is one of a CLOSED set (see
    validation_seed.GENERATORS); each type accepts only its own keys, anything else is refused.
    The plan holds data only: no code, no SQL, no expressions."""

    type: str
    value: str | int | float | bool | None = None  # constant
    values: list[str | int | float | bool] | None = None  # one_of
    prefix: str | None = None  # sequence (text) and email (local part)
    start: int | None = None  # sequence
    width: int | None = None  # sequence: zero padding
    min: str | int | None = (
        None  # int_range, decimal_range (decimals are strings: "10.50"), date_range
    )
    max: str | int | None = None
    places: int | None = None  # decimal_range: digits after the point
    ratio: float | None = None  # bool_ratio: share of true values, 0..1
    min_words: int | None = None  # words
    max_words: int | None = None
    entity: str | None = None  # reference: entity whose seeded rows are picked
    pick: str | None = None  # reference: cycle | random
    weights: dict[str, int] | None = None  # state: relative weight per state


class SpecSeedField(_SpecModel):
    field: str  # a field of the entity, or the column of a foreign key (e.g. customer_id)
    generator: SpecSeedGenerator


class SpecSeedEntity(_SpecModel):
    """`count` rows of `entity` (for each tenant when the entity is tenant-scoped)."""

    entity: str
    count: int
    fields: list[SpecSeedField] = Field(default_factory=list)


class SpecSeedProfile(_SpecModel):
    """One named, reproducible data set (demo, dev ...). The same profile always yields the same rows:
    `seed` drives every random choice and `as_of` is the only clock (no wall-clock time is read).
    `tenants` is the number of tenants to create and must be 0 unless the project is multi-tenant."""

    name: str
    seed: int
    as_of: str  # YYYY-MM-DD, midnight UTC; created_at of the first row
    tenants: int = 0
    entities: list[SpecSeedEntity] = Field(default_factory=list)


class Spec(_SpecModel):
    spec_version: int = SPEC_VERSION
    project: SpecProject
    entities: list[SpecEntity] = Field(default_factory=list)
    relations: list[SpecRelation] = Field(default_factory=list)
    # Phase 2 hooks (PLAN.md section 13): accepted by the schema, rejected by validation
    # while non-empty, because nothing stores or generates them yet.
    features: list[str] = Field(default_factory=list)
    auth: SpecAuth | None = None
    payments: SpecPayments | None = None
    storage: SpecStorage | None = None
    authorization: SpecAuthorization | None = None
    observability: SpecObservability | None = None
    deployment: SpecDeployment | None = None
    documents: SpecDocuments | None = None
    state_machines: list[SpecStateMachine] = Field(default_factory=list)
    settings: list[SpecSetting] = Field(default_factory=list)
    sequences: list[SpecSequence] = Field(default_factory=list)
    lists: list[SpecList] = Field(default_factory=list)
    history: list[SpecHistory] = Field(default_factory=list)
    hooks: list[SpecHook] = Field(default_factory=list)
    events: SpecEvents | None = None
    providers: SpecProviders | None = None
    notifications: SpecNotifications | None = None
    jobs: SpecJobs | None = None
    workflows: SpecWorkflows | None = None
    seed: list[SpecSeedProfile] = Field(default_factory=list)
    api_edge: SpecApiEdge | None = None
    webhooks: SpecWebhooks | None = None
    hook_effects: SpecHookEffects | None = None


def spec_hash(spec: Spec) -> str:
    """Stable SHA-256 of the spec's canonical JSON; identical specs hash identically."""
    canonical = json.dumps(
        spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
