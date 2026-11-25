import { projectId, time } from './connect-a'
import { spec as baseSpec } from './connect-a2'

export const connectSpec = {
  ...baseSpec,
  auth: { ...baseSpec.auth, roles: [...baseSpec.auth.roles, { name: 'admin', label: 'Admin' }] },
  entities: [{ name: 'Invoice', fields: [{ name: 'reference', type: 'str', required: true }] }],
}
export const providerSettings = {
  enabled: true, admin_role: 'admin', adapters: [{ kind: 'email', name: 'mail', settings: { region: 'eu' } }],
  timeout_seconds: 10, max_attempts: 3, breaker_failures: 5, breaker_reset_seconds: 30,
}
export const edgeSettings = {
  enabled: true, idempotency: { methods: ['POST'], ttl_hours: 24, max_response_bytes: 65536 },
  rate_limits: null, quotas: [], versioning: null,
}
export const platformSettings = {
  enabled: true, roles: ['admin'], entities: [{ entity: 'Invoice', fields: ['reference'], sandbox: true }],
  rate_limit: '60/minute', sandbox_rate_limit: '20/minute', key_ttl_days: 90,
  apps: [{ name: 'reporter', title: 'Reporter', scopes: ['Invoice'], events: ['invoice-ready'] }],
}
export const settings = { providers: providerSettings, 'api-edge': edgeSettings, 'api-platform': platformSettings }
export type Setting = keyof typeof settings
export const blockReply = (name: Setting, value: unknown, version = 3) => ({
  project_id: projectId, [name.replaceAll('-', '_')]: value, version, updated_at: null, row_version: version,
})

export const previewId = 'c4e1a466-1ed2-4711-b4bf-6a221f2c8a74'
export const previewPath = '/previews/' + previewId
export const preview = {
  id: previewId, project_id: projectId, workspace_id: null, is_preview: true, state: 'running',
  url_path: previewPath, created_at: time, last_request_at: time, expires_at: time, limits: {}, spec_hash: 'fixture', error: null,
}
export const platformPath = previewPath + '/platform'
export const app = { ...platformSettings.apps[0], scopes: ['Invoice', 'Vendor'], installed: false, installation_id: null, granted_scopes: [], installed_at: null }
export const catalogue = {
  ...platformSettings, entities: [
    { ...platformSettings.entities[0], plural_path: 'invoices' },
    { entity: 'Vendor', fields: ['name'], plural_path: 'vendors', sandbox: false },
  ],
}
export const apiKey = {
  id: '1e712e6f-0a11-49f3-a7f7-79a98835e700', name: 'Reporting key', prefix: 'key_demo', kind: 'api', app: null,
  environment: 'prod', scopes: ['Invoice'], created_at: time, expires_at: time, revoked_at: null, last_used_at: null, status: 'active',
}
export const audit = { id: 'audit-1', at: time, actor: 'preview-admin', action: 'key.create', target: apiKey.id, detail: { environment: 'prod' } }

export const batchId = '8b2ddbb2-c5af-456b-9bb8-bb8e84a5c71e'
export const row = { id: '7b879fbc-c080-4601-b917-29c4cb44b667', row_no: 1, raw: { reference: 'I-1' },
  record: null, status: 'rejected', errors: [{ field: 'reference', code: 'too_long', message: 'at most 2 characters' }] }
export const batch = {
  batch_id: batchId, entity: 'Invoice', status: 'previewed', counts: { total: 1, accepted: 0, rejected: 1, fixed: 0, duplicate: 0 },
  headers: ['reference'], mapping: { reference: 'reference' }, suggested_mapping: { reference: 'reference' }, sample: [row], rejected: [row],
}
