export type DbEngine = 'postgres'

export type FieldType =
  | 'string'
  | 'text'
  | 'integer'
  | 'bigint'
  | 'float'
  | 'decimal'
  | 'boolean'
  | 'date'
  | 'datetime'
  | 'uuid'
  | 'json'
  | 'enum'
  | 'file'

export type RelationKind = 'one_to_many' | 'many_to_many' | 'one_to_one'

export type OnDelete = 'cascade' | 'set_null' | 'restrict'

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Project {
  id: string
  name: string
  slug: string
  description: string | null
  db_engine: DbEngine
  version: number
  organization_id: string | null
  /** The project's org is waiting for deletion: opening it answers 423. */
  organization_locked?: boolean
  organization_deletion_scheduled_for?: string | null
  created_at: string
  updated_at: string
}

export interface EntityOptions {
  operations: string[]
  filterable: string[]
  sortable: string[]
  searchable: string[]
  default_page_size: number
  max_page_size: number
  soft_delete: boolean
}

export interface Entity {
  id: string
  project_id: string
  name: string
  table_name: string
  plural_path: string
  options: EntityOptions
  created_at: string
  updated_at: string
}

export interface Field {
  id: string
  entity_id: string
  name: string
  type: FieldType
  required: boolean
  unique: boolean
  indexed: boolean
  default: unknown
  max_length: number | null
  min_value: number | null
  max_value: number | null
  enum_values: string[] | null
  position: number
  created_at: string
  updated_at: string
}

export interface Relation {
  id: string
  project_id: string
  kind: RelationKind
  from_entity_id: string
  to_entity_id: string
  from_name: string
  to_name: string
  on_delete: OnDelete
  required: boolean
  created_at: string
  updated_at: string
}

export interface ApiErrorBody {
  code: string
  message: string
  details: unknown[]
}

export interface FieldInput {
  name: string
  type: FieldType
  required: boolean
  unique: boolean
  indexed: boolean
  default: unknown
  max_length: number | null
  min_value: number | null
  max_value: number | null
  enum_values: string[] | null
}

export interface EntityUpdate {
  name?: string
  table_name?: string
  plural_path?: string
  options?: EntityOptions
}

export interface ValidationIssue {
  path: string
  code: string
  message: string
}

export interface ValidationReport {
  valid: boolean
  issues: ValidationIssue[]
}

export interface PreviewFile {
  path: string
  size: number
}

export interface Preview {
  spec_hash: string
  total_files: number
  total_size: number
  files: PreviewFile[]
}

export interface GenerationSummary {
  id: string
  project_id: string
  spec_hash: string
  file_count: number
  total_size: number
  created_at: string
}

// ── Auth enums ──────────────────────────────────────────────────────

export type TokenStore = 'db' | 'redis'
export type JwtAlgorithm = 'HS256' | 'RS256'
export type DeletionMode = 'soft' | 'hard'
export type SmsProvider = 'twilio' | 'aws_sns' | 'vonage'
export type RowRule = 'owner' | 'role_scoped' | 'tenant' | 'custom_filter'
export type AuthOperation = 'list' | 'get' | 'create' | 'replace' | 'update' | 'delete' | 'head'
export type AuthCustomFieldType =
  | 'string'
  | 'text'
  | 'integer'
  | 'float'
  | 'boolean'
  | 'date'
  | 'datetime'
  | 'email'
  | 'phone'
  | 'url'
  | 'enum'

// ── Auth Config ──────────────────────────────────────────────────────────────

export interface SmtpConfig {
  host: string
  port: number
  use_tls: boolean
  from_email: string
  from_name: string
}

export interface SmsConfig {
  from_number: string
}

export interface AuthConfig {
  id: string
  project_id: string
  enabled: boolean
  /** Who manages users and tokens. Changed only by turning Keycloak on or off. */
  provider: AuthProvider
  token_store: TokenStore
  access_token_ttl_minutes: number
  refresh_token_ttl_days: number
  jwt_algorithm: JwtAlgorithm
  email_magic_link_enabled: boolean
  sms_otp_enabled: boolean
  otp_ttl_minutes: number
  email_verification_required: boolean
  invite_only: boolean
  multi_tenant: boolean
  deletion_mode: DeletionMode
  smtp_config: SmtpConfig | null
  sms_provider: SmsProvider | null
  sms_config: SmsConfig | null
  login_rate_limit: string
  register_rate_limit: string
  reset_rate_limit: string
  security_headers_enabled: boolean
  app_name: string | null
  app_url: string | null
  email_templates: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface AuthConfigCreate {
  enabled?: boolean
  token_store?: TokenStore
  access_token_ttl_minutes?: number
  refresh_token_ttl_days?: number
  jwt_algorithm?: JwtAlgorithm
  email_magic_link_enabled?: boolean
  sms_otp_enabled?: boolean
  otp_ttl_minutes?: number
  email_verification_required?: boolean
  invite_only?: boolean
  multi_tenant?: boolean
  deletion_mode?: DeletionMode
  smtp_config?: SmtpConfig | null
  sms_provider?: SmsProvider | null
  sms_config?: SmsConfig | null
  login_rate_limit?: string
  register_rate_limit?: string
  reset_rate_limit?: string
  security_headers_enabled?: boolean
  app_name?: string | null
  app_url?: string | null
  email_templates?: Record<string, unknown> | null
}

export interface AuthConfigUpdate {
  enabled?: boolean | null
  token_store?: TokenStore | null
  access_token_ttl_minutes?: number | null
  refresh_token_ttl_days?: number | null
  jwt_algorithm?: JwtAlgorithm | null
  email_magic_link_enabled?: boolean | null
  sms_otp_enabled?: boolean | null
  otp_ttl_minutes?: number | null
  email_verification_required?: boolean | null
  invite_only?: boolean | null
  multi_tenant?: boolean | null
  deletion_mode?: DeletionMode | null
  smtp_config?: SmtpConfig | null
  sms_provider?: SmsProvider | null
  sms_config?: SmsConfig | null
  login_rate_limit?: string | null
  register_rate_limit?: string | null
  reset_rate_limit?: string | null
  security_headers_enabled?: boolean | null
  app_name?: string | null
  app_url?: string | null
  email_templates?: Record<string, unknown> | null
}

// ── Roles ────────────────────────────────────────────────────────────────────

export interface ProjectRole {
  id: string
  project_id: string
  name: string
  label: string
  is_default: boolean
  self_assignable: boolean
  invite_only: boolean
  inherits_from: string | null
  position: number
  created_at: string
  updated_at: string
}

export interface ProjectRoleCreate {
  name: string
  label: string
  is_default?: boolean
  self_assignable?: boolean
  invite_only?: boolean
  inherits_from?: string | null
  position?: number
}

export interface ProjectRoleUpdate {
  label?: string | null
  is_default?: boolean | null
  self_assignable?: boolean | null
  invite_only?: boolean | null
  inherits_from?: string | null
  position?: number | null
}

// ── Permissions ──────────────────────────────────────────────────────────────

export interface ProjectPermission {
  id: string
  project_id: string
  entity_id: string
  operation: AuthOperation
  roles: string[]
  row_rule: RowRule | null
  custom_filter_field: string | null
  custom_filter_value: string | null
  created_at: string
  updated_at: string
}

export interface PermissionEntry {
  entity_id: string
  operation: AuthOperation
  roles?: string[]
  row_rule?: RowRule | null
  custom_filter_field?: string | null
  custom_filter_value?: string | null
}

export interface ProjectPermissionBulkUpsert {
  permissions: PermissionEntry[]
}

// ── Auth Custom Fields ───────────────────────────────────────────────────────

export interface AuthCustomField {
  id: string
  project_id: string
  name: string
  label: string
  type: AuthCustomFieldType
  required: boolean
  unique: boolean
  indexed: boolean
  min_length: number | null
  max_length: number | null
  min_value: number | null
  max_value: number | null
  default_value: string | null
  enum_values: string[] | null
  extra: Record<string, unknown> | null
  position: number
  created_at: string
  updated_at: string
}

export interface AuthCustomFieldCreate {
  name: string
  label: string
  type: AuthCustomFieldType
  required?: boolean
  unique?: boolean
  indexed?: boolean
  min_length?: number | null
  max_length?: number | null
  min_value?: number | null
  max_value?: number | null
  default_value?: string | null
  enum_values?: string[] | null
  extra?: Record<string, unknown> | null
  position?: number
}

export interface AuthCustomFieldUpdate {
  label?: string | null
  required?: boolean | null
  unique?: boolean | null
  indexed?: boolean | null
  min_length?: number | null
  max_length?: number | null
  min_value?: number | null
  max_value?: number | null
  default_value?: string | null
  enum_values?: string[] | null
  extra?: Record<string, unknown> | null
  position?: number | null
}

// ── Keycloak ──────────────────────────────────────────────────────────────────

export type AuthProvider = 'builtin' | 'keycloak'
export type KeycloakMode = 'own' | 'shared'
export type MfaMode = 'off' | 'optional' | 'required'
export type IdpType = 'google' | 'microsoft' | 'github' | 'oidc'

export interface IdentityProvider {
  alias: string
  type: IdpType
  display_name: string | null
  client_id: string
  tenant_id: string | null
  hosted_domain: string | null
  issuer: string | null
  authorization_url: string | null
  token_url: string | null
  jwks_url: string | null
  userinfo_url: string | null
}

export interface KeycloakWrite {
  mode: KeycloakMode
  realm: string | null
  api_client_id: string | null
  web_client_id: string | null
  redirect_uris: string[]
  password_min_length: number
  mfa: MfaMode
  session_idle_minutes: number
  session_max_hours: number
  audit_retention_days: number
  identity_providers: IdentityProvider[]
  source_project_id: string | null
}

export interface KeycloakConfig extends Omit<KeycloakWrite, 'realm' | 'api_client_id' | 'web_client_id'> {
  id: string
  project_id: string
  /** True while this project uses Keycloak. */
  active: boolean
  realm: string
  api_client_id: string
  web_client_id: string
  created_at: string
  updated_at: string
}

export interface KeycloakImpact {
  action: 'enable' | 'disable'
  provider: AuthProvider
  can_proceed: boolean
  blockers: string[]
  warnings: string[]
  dependents: { id: string; name: string }[]
}

// ── Payments ─────────────────────────────────────────────────────────────────

export type PaymentProvider = 'stripe' | 'razorpay'
export type PaymentsProfile = 'small' | 'medium' | 'large'
export type PaymentsAvailability = 'single' | 'ha'
export type WebhookMode = 'inline' | 'queued'

export interface PaymentsPayable {
  entity: string
  amount_field: string
  currency: string | null
  currency_field: string | null
  status_field: string
  status_pending: string
  status_paid: string
  status_partially_refunded: string
  status_refunded: string
}

export interface PaymentsRoles {
  create: string[]
  read: string[]
  read_all: string[]
  refund: string[]
  approve_refund: string[]
  operate: string[]
}

export interface PaymentsScale {
  profile: PaymentsProfile
  peak_payments_per_minute: number | null
  peak_webhooks_per_minute: number | null
  db_max_connections: number
  availability: PaymentsAvailability
  pgbouncer: boolean
  kubernetes: boolean
  webhook_mode: WebhookMode | null
  api_replicas: number | null
  server_workers: number | null
  worker_replicas: number | null
  worker_concurrency: number | null
  pool_size: number | null
  webhook_events_retention_days: number
  jobs_retention_days: number
}

export interface PaymentsSecurity {
  webhook_tolerance_seconds: number
  webhook_max_body_bytes: number
  webhook_ip_allowlist_enabled: boolean
  idempotency_ttl_hours: number
  audit_retention_days: number
  secrets_from_files: boolean
  allow_payer_edits: boolean
}

export interface PaymentsConfig {
  id: string
  project_id: string
  enabled: boolean
  provider: PaymentProvider
  payable: PaymentsPayable | null
  currencies: string[]
  max_amount_minor: number
  success_urls: string[]
  cancel_urls: string[]
  roles: PaymentsRoles
  refund_approval_threshold_minor: number | null
  scale: PaymentsScale
  security: PaymentsSecurity
  created_at: string
  updated_at: string
}

export type PaymentsWrite = Omit<PaymentsConfig, 'id' | 'project_id' | 'enabled' | 'created_at' | 'updated_at'>

export interface PaymentsImpact {
  action: 'enable' | 'disable'
  enabled: boolean
  can_proceed: boolean
  blockers: string[]
  warnings: string[]
}

export interface PaymentsSizing {
  payments_per_minute: number
  webhooks_per_minute: number
  webhook_mode: WebhookMode
  api_replicas: number
  server_workers: number
  pool_size: number
  max_overflow: number
  worker_replicas: number
  worker_concurrency: number
  worker_pool_size: number
  poll_interval_seconds: number
  batch_size: number
  api_replicas_max: number
  worker_replicas_max: number
  total_db_connections: number
  connection_budget: number
  needs_pgbouncer: boolean
  pgbouncer_pool_size: number | null
  warnings: string[]
  assumptions: string[]
}

export interface PaymentsSizingResult {
  sizing: PaymentsSizing
  issues: ValidationIssue[]
}

// ── File storage ─────────────────────────────────────────────────────────────

export type StorageBackend = 's3' | 'minio'
export type DownloadMode = 'proxy' | 'presigned'

export interface StorageRoles {
  upload: string[]
  share: string[]
  read: string[]
  read_all: string[]
  delete: string[]
  delete_all: string[]
  operate: string[]
}

export interface StorageSecurity {
  audit_retention_days: number
  audit_ip: boolean
  rescan_after_days: number
  scan_timeout_seconds: number
}

export interface StorageConfig {
  id: string
  project_id: string
  enabled: boolean
  backend: StorageBackend
  bucket: string
  region: string | null
  key_prefix: string
  allowed_types: string[]
  max_file_mb: number
  user_quota_mb: number | null
  uploads_per_hour: number
  download_mode: DownloadMode
  allow_inline_images: boolean
  roles: StorageRoles
  security: StorageSecurity
  created_at: string
  updated_at: string
}

export type StorageWrite = Omit<StorageConfig, 'id' | 'project_id' | 'enabled' | 'created_at' | 'updated_at'>

export interface StorageImpact {
  action: 'enable' | 'disable'
  enabled: boolean
  can_proceed: boolean
  blockers: string[]
  warnings: string[]
}


// ── Accounts, API tokens, members, admin console ─────────────────────────────────────────

export type PlatformRole = 'customer' | 'platform_support' | 'platform_admin'
export type MemberRole = 'viewer' | 'editor' | 'owner'

export interface UserAccount {
  id: string
  email: string
  name: string
  platform_role: PlatformRole
  status: 'active' | 'suspended'
  must_change_password: boolean
  created_at: string
  last_login_at: string | null
  default_organization_id?: string | null
  /** TOTP is turned on for this account. */
  mfa_enabled?: boolean
}

export interface SessionResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: UserAccount
}

export interface ApiTokenInfo {
  id: string
  name: string
  description: string | null
  public_id: string
  scopes: string[]
  project_id: string | null
  created_at: string
  expires_at: string
  last_used_at: string | null
  last_mcp_use_at: string | null
  revoked_at: string | null
}

export interface ApiTokenCreated extends ApiTokenInfo {
  token: string
}

/** The owner's view of a token pinned to their project: who created it. */
export interface ProjectToken extends ApiTokenInfo {
  user_id: string
  user_email: string
}

export interface Member {
  user_id: string
  email: string
  name: string
  role: MemberRole
  mcp_enabled: boolean
  created_at: string
}

export interface AdminUser extends UserAccount {
  failed_logins: number
  locked_until: string | null
  project_count: number
}

export interface AdminProject {
  id: string
  name: string
  slug: string
  created_at: string
  owner_emails: string[]
  entity_count: number
}

export interface AuditEntry {
  id: number
  at: string
  actor_id: string | null
  actor_email: string | null
  via: string
  action: string
  target_type: string | null
  target_id: string | null
  project_id: string | null
  organization_id?: string | null
  result: 'ok' | 'denied' | 'error'
  client_ip: string | null
  detail: Record<string, unknown> | null
}

export interface AdminStats {
  users: number
  active_users: number
  suspended_users: number
  admins: number
  projects: number
  api_tokens: number
  failed_logins_24h: number
}

export interface PlatformSettings {
  environment: string
  signup_mode: string
  access_token_minutes: number
  refresh_token_days: number
  admin_refresh_token_hours: number
  login_max_failures: number
  lockout_minutes: number
  trust_proxy_headers: boolean
  docs_enabled: boolean
  cors_origins: string[]
}

// ── Documents (PDF) ─────────────────────────────────────────────────────────

export interface DocumentTemplate {
  id: string
  title: string
  kind: string
  entity: string | null
  compute: string | null
  roles: string[]
  template: {
    title?: string
    page?: { size?: string; orientation?: string; margin_mm?: number }
    header?: string
    footer?: string
    blocks: Record<string, unknown>[]
  }
}

export interface DocumentsSettings {
  project_id: string
  enabled: boolean
  rate_limit: string
  templates: DocumentTemplate[]
  version: number
  updated_at: string | null
}

export type DocumentsWrite = Omit<DocumentsSettings, 'project_id' | 'version' | 'updated_at'> & { expected_version?: number }

export interface LibraryTemplate {
  id: string
  title: string
  industries: string[]
  why: string
  compute: string | null
  template: DocumentTemplate['template']
  sample: Record<string, unknown>
}

// ── Deployment (CI/CD and Terraform) ────────────────────────────────────────

export interface DeployEnvironment {
  name: string
  profile: string
  min_instances: number | null
  max_instances: number | null
  cpu: number | null
  memory: number | null
  db_storage_gb: number | null
  db_high_availability: boolean | null
  deletion_protection: boolean | null
}

export interface DeploymentSettings {
  project_id: string
  enabled: boolean
  cloud: string
  region: string
  github_repo: string
  environments: DeployEnvironment[]
  version: number
  updated_at: string | null
}

export type DeploymentWrite = Omit<DeploymentSettings, 'project_id' | 'version' | 'updated_at'> & {
  expected_version?: number
}

export interface DeploymentPlan {
  cloud: string
  region: string
  environments: {
    name: string
    profile: string
    cpu: number
    memory: number
    min_instances: number
    max_instances: number
    db_class: string
    db_storage_gb: number
    db_high_availability: boolean
    deletion_protection: boolean
    tfvars: string
  }[]
  valid_sizes: [number, number][]
  notes: string[]
}

// ── Observability (OpenTelemetry) ───────────────────────────────────────────

export interface ObservabilitySettings {
  project_id: string
  enabled: boolean
  service_name: string | null
  sample_ratio: number
  metrics: boolean
  db_spans: boolean
  exclude_paths: string[]
  extra_redact_keys: string[]
  local_stack: boolean
  expected_rps: number | null
  version: number
  updated_at: string | null
  recommended_sample_ratio: number
  default_service_name: string
  redacted_keys: string[]
}

export type ObservabilityWrite = Omit<
  ObservabilitySettings,
  'project_id' | 'version' | 'updated_at' | 'recommended_sample_ratio' | 'default_service_name' | 'redacted_keys'
> & { expected_version?: number }

// ── Authorization (rbac / abac / pbac) ──────────────────────────────────────

export type AuthorizationModel = 'rbac' | 'abac' | 'pbac'

/** One side of a comparison. Exactly one key is set. */
export type Operand =
  | { subject: string }
  | { resource: string }
  | { env: string }
  | { literal: unknown }

export interface PolicyLeaf {
  left: Operand
  op: string
  right?: Operand
}

export interface PolicyGroup {
  all?: PolicyCondition[]
  any?: PolicyCondition[]
}

export type PolicyCondition = PolicyGroup | PolicyLeaf

export interface Policy {
  id: string
  description: string
  effect: 'allow' | 'deny'
  actions: string[]
  when: PolicyCondition | null
}

export interface AuthorizationSettings {
  project_id: string
  model: AuthorizationModel
  policies: Policy[]
  attachments: Record<string, string[]>
  version: number
  updated_at: string | null
}

export interface AuthorizationWrite {
  model: AuthorizationModel
  policies: Policy[]
  attachments: Record<string, string[]>
  expected_version?: number
}

export interface SimulateRequest {
  entity: string
  op: string
  subject: Record<string, unknown>
  resource: Record<string, unknown> | null
  env: Record<string, unknown>
}

export interface SimulateTraceLeaf {
  text: string
  result: boolean
}

export interface SimulateTrace {
  policy: string
  effect: 'allow' | 'deny'
  condition: string
  condition_met: boolean
  leaves: SimulateTraceLeaf[]
}

export interface SimulateResult {
  allowed: boolean
  reason: string
  allow_matched: string[]
  deny_matched: string[]
  trace: SimulateTrace[]
}

export interface CoverageItem {
  policy: string
  who: string
  condition: string
  unconditional: boolean
}

export interface CoverageRow {
  entity: string
  op: string
  state: 'closed' | 'conditional' | 'open'
  allow: CoverageItem[]
  deny: CoverageItem[]
}

export interface CoverageResult {
  model: AuthorizationModel
  rows: CoverageRow[]
}

export interface RecommendAnswers {
  roles: number
  ownership_rules: boolean
  tenant_rules: boolean
  time_or_network_rules: boolean
  per_record_rules: boolean
  deny_rules: boolean
  audit_needs: boolean
  policy_editors: 'developers' | 'admins'
  public_routes: boolean
}

export interface Recommendation {
  model: AuthorizationModel
  scores: Record<string, number>
  reasons: string[]
  cautions: string[]
  alternatives: string[]
}

/** The slice of the project spec the policy editor needs. */
export interface SpecForPolicies {
  entities: {
    name: string
    options: { operations?: string[] }
    fields: { name: string; type: string; enum_values?: string[] | null }[]
  }[]
  auth: {
    multi_tenant: boolean
    roles: { name: string; label: string }[]
    registration?: { custom_fields?: { name: string; type: string }[] }
  } | null
}

// ── Organizations, plans & quotas (Platform SaaS Phase B) ──────────────────

export type OrgRole = 'owner' | 'admin' | 'member'

export interface Organization {
  id: string
  name: string
  slug: string
  kind: 'personal' | 'team'
  created_at: string
  my_role: OrgRole
  member_count: number
  /** Set while a deletion request waits out its grace period. The org is locked meanwhile. */
  deletion_requested_at?: string | null
  deletion_scheduled_for?: string | null
  /** Security policies (§8): members need two-factor; absolute session cap in hours (null = default). */
  require_mfa?: boolean
  session_ttl_hours?: number | null
}

/** `details[0]` of a 423 `org_deletion_pending` refusal. */
export interface OrgLockedDetail {
  organization_id?: string
  organization_slug?: string
  organization_name?: string
  deletion_scheduled_for: string | null
}

export interface PlanInfo {
  id: string
  display_name: string
  max_seats: number | null
  max_projects: number | null
  max_api_tokens: number | null
  max_mcp_tokens: number | null
  allow_sso: boolean
  allow_scim: boolean
  allow_mcp: boolean
  monthly_price_usd: number // cents
  is_public: boolean
}

export interface OrgUsage {
  seats_used: number
  seats_cap: number | null
  pending_invites: number
  projects_used: number
  projects_cap: number | null
  api_tokens_used: number // the viewer's own tokens in this org
  api_tokens_cap: number | null // per member
  mcp_tokens_used: number
  mcp_tokens_cap: number | null
}

export interface OrgPlan {
  plan: PlanInfo
  subscription: {
    organization_id: string
    plan_id: string
    status: 'active' | 'past_due' | 'canceled' | 'trial'
    trial_ends_at: string | null
    current_period_end: string | null
    seat_override: number | null
    project_override: number | null
  }
  usage: OrgUsage
  checkout_available: boolean
  upgrades: PlanInfo[]
  /** The org has a Stripe customer: owners/admins can open "Manage billing". */
  portal_available: boolean
}

/** `details[0]` of a 402 quota refusal. */
export interface QuotaDetail {
  resource: 'seats' | 'projects' | 'api_tokens' | 'mcp_tokens' | 'sso' | 'scim'
  plan: string
  /** null when the refusal is not about a cap (reason 'past_due'). */
  cap: number | null
  used: number
  /** 'cap': the plan's counter is full. 'past_due': the last payment failed. */
  reason?: 'cap' | 'past_due' | 'feature'
  organization_slug: string | null
}

export interface AdminOrg {
  /** The org's consent to "view as" (Security policies); default true. */
  allow_impersonation: boolean
  id: string
  name: string
  slug: string
  kind: 'personal' | 'team'
  created_at: string
  deleted_at: string | null
  member_count: number
  project_count: number
  plan_id: string
  status: string
  seat_override: number | null
  project_override: number | null
  stripe_customer_id: string | null
  stripe_subscription_id: string | null
  current_period_end: string | null
  trial_ends_at: string | null
  mrr_cents: number
  last_activity_at: string | null
  deletion_requested_at?: string | null
  deletion_scheduled_for?: string | null
  /** SSO status (§7): protocol is null when no connection is configured. */
  sso_protocol?: SsoProtocol | null
  sso_active?: boolean
  sso_verified_domains?: number
  sso_last_test_at?: string | null
  sso_last_test_result?: string | null
  require_mfa?: boolean
  session_ttl_hours?: number | null
  /** SCIM status (§12.E.4). */
  scim_configured?: boolean
  scim_active?: boolean
  /** Active SCIM-provisioned people. */
  scim_users?: number
  scim_last_sync_at?: string | null
  scim_token_created_at?: string | null
}

export interface AdminOrgMember {
  user_id: string
  email: string
  name: string
  role: OrgRole
  joined_at: string
  status: 'active' | 'suspended'
  last_login_at: string | null
  mfa_enabled?: boolean
}

export interface AdminOrgProject {
  id: string
  name: string
  slug: string
  created_at: string
  updated_at: string
  entity_count: number
}

export interface AdminSubscription {
  organization_id: string
  organization_slug: string
  organization_name: string
  plan_id: string
  status: string
  current_period_end: string | null
  trial_ends_at: string | null
  stripe_customer_id: string | null
  stripe_subscription_id: string | null
  seat_override: number | null
  updated_at: string
}

export interface AdminInsights {
  signups_per_day: { day: string; count: number }[]
  orgs_per_day: { day: string; count: number }[]
  total_orgs: number
  active_orgs_7d: number
  total_projects: number
  mcp_calls_24h: number
  denied_by_quota_7d: number
}

export interface ReconcileReport {
  checked: number
  changed: number
  failed: number
  trials_expired: number
}

/** `GET /orgs/{slug}/audit` — no details or IPs (§7.1). */
export interface OrgAuditEntry {
  id: number
  at: string
  actor_email: string | null
  via: string
  action: string
  target_type: string | null
  target_id: string | null
  project_id: string | null
  result: 'ok' | 'denied' | 'error'
}

// ── Org console (Platform SaaS Phase A step 6) ─────────────────────────────

export interface OrgMember {
  user_id: string
  email: string
  name: string
  role: OrgRole
  joined_at: string
  status?: 'active' | 'suspended'
  last_login_at?: string | null
  mfa_enabled?: boolean
}

export interface OrgInvitation {
  id: string
  organization_id: string
  organization_slug: string
  organization_name: string
  email: string
  role: OrgRole
  status: 'pending' | 'accepted' | 'revoked' | 'expired'
  created_at: string
  expires_at: string
}

/** Returned once, when the invitation is created. */
export interface OrgInvitationCreated extends OrgInvitation {
  token: string
  invite_url: string
  emailed: boolean // false when the platform has no SMTP configured
}

/** Body of `PUT /admin/plans/{id}`: everything but the id. */
export type PlanWrite = Omit<PlanInfo, 'id'>

// ── Two-factor authentication (§4.4) ───────────────────────────────────────

/** `POST /account/login` or `/admin/login` when a second step is needed. */
export interface MfaChallenge {
  mfa_required: true
  /** true: the account has no TOTP yet and must set it up now (platform staff). */
  enrollment_required: boolean
  mfa_token: string
  expires_in: number
  methods: ('totp' | 'recovery_code')[]
}

export type LoginResult = SessionResponse | MfaChallenge

export function isMfaChallenge(result: LoginResult): result is MfaChallenge {
  return 'mfa_required' in result && result.mfa_required === true
}

export interface TotpSetup {
  secret: string
  otpauth_uri: string
}

/** Turning TOTP on returns a new session that counts as MFA'd, plus the codes, shown once. */
export interface SessionWithRecoveryCodes extends SessionResponse {
  recovery_codes: string[]
}

export interface MfaStatus {
  totp_enabled: boolean
  enabled_at: string | null
  recovery_codes_left: number
  /** This session was started with a second factor. */
  session_mfa: boolean
  required_for_staff: boolean
  required_by: { organization_id: string; slug: string; name: string }[]
  /** SSO-only accounts: the identity provider handles two-factor. */
  sso_only: boolean
}

/** `details[0]` of a 403 `org_mfa_required` refusal. */
export interface OrgMfaDetail {
  organization_id: string
  organization_slug: string
  organization_name: string
  mfa_enabled: boolean
}

// ── Security policies (§8) ─────────────────────────────────────────────────

export interface OrgPolicies {
  require_mfa: boolean
  session_ttl_hours: number | null
  members_without_mfa: number
  default_session_hours: number
  /** §7.1: platform support may "view as" members while this is on (default on). */
  allow_impersonation: boolean
}

export interface OrgPoliciesUpdate {
  require_mfa?: boolean
  session_ttl_hours?: number | null
  allow_impersonation?: boolean
}

// ── Impersonation, "view as" (§4.5, §7.1) ───────────────────────────────────

/** The only answer that carries the viewing token; the operator's tab hands it over and drops it. */
export interface ImpersonationStarted {
  session_id: string
  access_token: string
  expires_in: number
  expires_at: string
  user_email: string
  organization_id: string
  organization_slug: string
}

/** What the "You are viewing as …" banner shows. */
export interface ImpersonationState {
  session_id: string
  operator_email: string
  user_email: string
  organization_id: string
  organization_slug: string
  organization_name: string
  expires_at: string
  writes_allowed: boolean
  writes_until: string | null
}

export interface ImpersonationDigest {
  since: string
  until: string
  sessions: Record<string, unknown>[]
  refused: number
  text: string
}

export interface ImpersonationSessionRow {
  id: string
  operator_email: string
  user_email: string
  organization_id: string
  organization_slug: string
  reason: string
  created_at: string
  expires_at: string
  ended_at: string | null
  writes_until: string | null
  active: boolean
}

// ── Single sign-on (§4.2) ──────────────────────────────────────────────────

export type SsoProtocol = 'saml' | 'oidc'

export interface LoginDiscovery {
  method: 'sso' | 'password'
  login_url?: string | null
  organization_name?: string | null
}

export interface SsoDomain {
  domain: string
  verified_at: string | null
  created_at: string
  dns_record_type?: string
  dns_record_name: string
  dns_record_value: string
}

export interface SsoConfig {
  configured: boolean
  allowed_by_plan: boolean
  protocol?: SsoProtocol | null
  active?: boolean
  idp_entity_id?: string | null
  idp_sso_url?: string | null
  idp_certificate?: { sha256_fingerprint: string; not_after: string; subject: string } | null
  oidc_discovery_url?: string | null
  oidc_client_id?: string | null
  oidc_client_secret_set?: boolean
  jit_enabled?: boolean
  jit_role?: 'member' | 'admin'
  trust_unverified_email?: boolean
  updated_at?: string | null
  last_test?: { at: string; result: string; tested_by_email?: string | null } | null
  sp: {
    entity_id: string
    acs_url: string
    metadata_url: string
    oidc_redirect_uri: string
    login_url: string
  }
  domains: SsoDomain[]
}

export interface SsoConfigWrite {
  protocol: SsoProtocol
  idp_entity_id?: string | null
  idp_sso_url?: string | null
  idp_cert_pem?: string | null
  oidc_discovery_url?: string | null
  oidc_client_id?: string | null
  /** Write-only. Leave out to keep the stored secret. */
  oidc_client_secret?: string | null
  jit_enabled?: boolean
  jit_role?: 'member' | 'admin'
  trust_unverified_email?: boolean
}

export interface SsoCheck {
  ok: boolean
  protocol: string | null
  active: boolean
  checks: { name: string; status: 'ok' | 'warning' | 'error'; detail?: string | null }[]
}

// ── SCIM provisioning setup (§4.3, §12.E.5) ─────────────────────────────────

export type ScimRole = 'owner' | 'admin' | 'member'

export interface ScimGroupSummary {
  display_name: string
  members: number
  mapped_role: string | null
}

export interface ScimConfig {
  configured: boolean
  allowed_by_plan: boolean
  active: boolean
  /** Paste into the IdP as the SCIM base / tenant URL. */
  base_url: string
  /** base_url + "/Users", for IdPs that ask for it. */
  users_url: string
  /** Last 4 characters of the token; null after an operator rotation (nobody knows the token). */
  token_hint: string | null
  token_created_at: string | null
  created_at: string | null
  last_sync_at: string | null
  /** Lower-cased group name -> org role. */
  group_roles: Record<string, ScimRole>
  active_users: number
  deactivated_users: number
  groups: ScimGroupSummary[]
}

/** POST /orgs/{slug}/scim/token. `token` is shown this once. */
export interface ScimToken extends ScimConfig {
  token: string
}

export interface ScimConfigUpdate {
  active?: boolean
  group_roles?: Record<string, ScimRole>
}

// ── Behaviour: state machines (GET /projects/{id}/behavior/state-machines, /behavior/issues) ──
// Fields the API defaults are optional here (the API always sends them; this matches api/contract.test.ts).
export interface TransitionBody {
  name: string
  from_states?: string[]
  to_state: string
  when?: string | null
  roles?: string[]
  auto?: boolean
}

export interface StateMachineBody {
  entity: string
  field: string
  initial: string
  transitions?: TransitionBody[]
}

export interface StateMachinesRead {
  project_id: string
  version: number
  updated_at?: string | null
  state_machines: StateMachineBody[]
}

export interface BehaviorIssues {
  issues: ValidationIssue[]
}

// ── Behaviour: runtime settings, sequences, lists, change history (F1-6A; shapes in app/schemas/behavior.py) ──
export interface SettingBody {
  key: string
  type?: string
  default?: string | number | boolean | null
  label?: string | null
  description?: string | null
  minimum?: string | number | null
  maximum?: string | number | null
  max_length?: number | null
  read_roles?: string[]
  edit_roles?: string[]
}
export interface SequenceBody {
  name: string
  prefix?: string
  padding?: number
  start?: number
  per_tenant?: boolean
  reset_yearly?: boolean
  view_roles?: string[]
}
export interface ListItemBody {
  value: string
  label: string
  color?: string | null
  locked?: boolean
}
export interface ListBody {
  name: string
  label?: string | null
  items?: ListItemBody[]
  max_items?: number
  edit_roles?: string[]
}
export interface HistoryBody {
  entity: string
  fields?: string[]
  retention_days: number
  view_roles?: string[]
}
interface SectionRead {
  project_id: string
  version: number
  updated_at?: string | null
}
export interface SettingsRead extends SectionRead { settings: SettingBody[] }
export interface SequencesRead extends SectionRead { sequences: SequenceBody[] }
export interface ListsRead extends SectionRead { lists: ListBody[] }
export interface HistoryRead extends SectionRead { history: HistoryBody[] }

// ── Behaviour: custom-logic hooks (F1-5; shapes in app/schemas/behavior.py HookBody) ──
export interface HookFieldBody {
  name: string
  type?: string
  required?: boolean
}
export interface HookModelBody {
  name: string
  fields?: HookFieldBody[]
}
export interface HookBudgetBody {
  cpu_ms?: number
  rows?: number
  outbound_calls?: number
}
export interface HookBody {
  name: string
  point: string
  kind?: string
  input: HookModelBody
  output: HookModelBody
  failure_policy?: string | null
  fallback?: Record<string, string | number | boolean> | null
  budget?: HookBudgetBody
  reads?: string[]
}
export interface HooksRead extends SectionRead { hooks: HookBody[] }

// ── Behaviour: seed profiles (F1-6B; shapes in app/schemas/behavior.py Seed*Body) ──
export interface SeedGeneratorBody {
  type: string
  value?: string | number | boolean | null
  values?: (string | number | boolean)[] | null
  prefix?: string | null
  start?: number | null
  width?: number | null
  min?: string | number | null
  max?: string | number | null
  places?: number | null
  ratio?: number | null
  min_words?: number | null
  max_words?: number | null
  entity?: string | null
  pick?: string | null
  weights?: Record<string, number> | null
}
export interface SeedFieldBody { field: string; generator: SeedGeneratorBody }
export interface SeedEntityBody { entity: string; count: number; fields?: SeedFieldBody[] }
export interface SeedProfileBody { name: string; seed: number; as_of: string; tenants?: number; entities?: SeedEntityBody[] }
export interface SeedRead extends SectionRead { seed: SeedProfileBody[] }

// ── Readiness board (F1-2; shapes in app/schemas/status.py) ──
export interface StatusSection {
  id: string
  label: string
  configured: boolean
  issue_count: number
}

export interface NextStep {
  id: string
  title: string
  reason: string
  section: string
}

export interface ProjectStatus {
  ready: boolean
  issues: ValidationIssue[]
  counts: Record<string, number>
  sections: StatusSection[]
  next_step: NextStep
}

// ── Build > Rules expression checker (F1-3; shapes in app/schemas/behavior.py) ──
export interface ExpressionCheckBody {
  entity: string
  expression: string
  expect?: 'bool' | 'any'
}

export interface ExpressionError {
  message: string
  pos: number
}

export interface ExpressionField {
  name: string
  type: string
  nullable: boolean
}

export interface ExpressionCheckRead {
  ok: boolean
  type?: string | null
  error?: ExpressionError | null
  fields: ExpressionField[]
}
