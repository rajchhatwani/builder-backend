export const projectId = '8e87dc58-c920-4ca1-93af-aed0ed17397f'
export const root = '/projects/' + projectId
export const time = '2026-01-10T12:00:00Z'
export const user = {
  id: 'owner', name: 'Mina Chen', email: 'mina@example.test', platform_role: 'customer', email_verified_at: time,
}
export const members = [
  { user_id: user.id, email: user.email, name: user.name, role: 'owner', mcp_enabled: true, created_at: time },
  { user_id: 'alex', email: 'alex@example.test', name: 'Alex Bench', role: 'editor', mcp_enabled: false, created_at: time },
]
export const model = {
  auth: { enabled: true, roles: [{ name: 'employee', label: 'Employee' }], multi_tenant: false },
  entities: [{ name: 'Invoice', fields: [
    { name: 'amount', type: 'decimal', required: true, min_value: 1 },
    { name: 'payment_status', type: 'enum', required: true, enum_values: ['waiting', 'paid', 'partly_refunded', 'refunded'] },
    { name: 'attachment', type: 'file', required: false },
  ] }],
}
const config = { id: 'config', project_id: projectId, enabled: true, created_at: time, updated_at: time }
export const payments = {
  ...config,
  provider: 'stripe',
  payable: {
    entity: 'Invoice', amount_field: 'amount', currency: 'USD', currency_field: null, status_field: 'payment_status',
    status_pending: 'waiting', status_paid: 'paid', status_partially_refunded: 'partly_refunded', status_refunded: 'refunded',
  },
  currencies: ['USD', 'JPY'], success_urls: ['https://example.test/success'], cancel_urls: ['https://example.test/cancel'],
  max_amount_minor: 100_000, roles: { create: ['employee'], read: ['employee'], refund: [], approve_refund: [], read_all: [], operate: [] },
  refund_approval_threshold_minor: null,
  scale: { profile: 'small', availability: 'single', db_max_connections: 100, webhook_events_retention_days: 90, jobs_retention_days: 30 },
  security: { webhook_tolerance_seconds: 300, webhook_max_body_bytes: 262_144, idempotency_ttl_hours: 48,
    audit_retention_days: 2555, secrets_from_files: true },
}
export const sizing = {
  payments_per_minute: 10, webhooks_per_minute: 50, webhook_mode: 'inline', api_replicas: 1, server_workers: 1,
  pool_size: 5, max_overflow: 2, worker_replicas: 1, worker_concurrency: 1, worker_pool_size: 3, poll_interval_seconds: 1,
  batch_size: 1, api_replicas_max: 2, worker_replicas_max: 2, total_db_connections: 12, connection_budget: 80,
  needs_pgbouncer: false, pgbouncer_pool_size: null, assumptions: ['These are estimates.'], warnings: [],
}
export const storage = {
  ...config,
  backend: 's3', bucket: 'invoice-files', key_prefix: 'uploads', region: 'eu-west-1', allowed_types: ['application/pdf'],
  max_file_mb: 25, user_quota_mb: null, uploads_per_hour: 60, download_mode: 'proxy', allow_inline_images: false,
  roles: { upload: ['employee'], read: ['employee'], share: [], read_all: [], delete: ['employee'], delete_all: [], operate: ['employee'] },
  security: { audit_ip: true, audit_retention_days: 2555, rescan_after_days: 30, scan_timeout_seconds: 120 },
}
export const token = {
  id: 'token-1', user_id: user.id, user_email: user.email, name: 'Project assistant', description: 'Read invoice metadata',
  public_id: 'public-integration', project_id: projectId, scopes: ['mcp:read'], created_at: time,
  expires_at: '2026-05-10T12:00:00Z', last_used_at: time, last_mcp_use_at: time, revoked_at: null,
}
