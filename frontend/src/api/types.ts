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
