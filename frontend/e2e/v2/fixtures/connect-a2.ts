import { model, projectId, time } from './connect-a'

export const notificationType = {
  name: 'invoice_ready', category: 'optional', channels: ['email', 'sms'],
  variables: ['customer'], default_enabled: true, on_event: 'invoice.created', recipient_key_field: 'id',
  address_fields: { email: 'id', sms: 'id' },
  templates: [
    { channel: 'email', subject: 'Invoice ready for {{ customer }}', body: 'Your invoice is ready.', html: false },
    { channel: 'sms', subject: '', body: 'Your invoice is ready, {{ customer }}.', html: false },
  ],
}
export const notifications = {
  enabled: true, admin_role: 'employee', types: [notificationType], max_attempts: 5, backoff_seconds: 30, retention_days: 90,
}
export const webhooks = {
  enabled: true, admin_role: 'employee', events: ['invoice.created'], allow_http: false, allowed_ports: [],
  timeout_seconds: 10, max_consecutive_failures: 5, max_payload_bytes: 262144, secret_overlap_hours: 24,
  inbound: [{ name: 'invoice_status', tolerance_seconds: 300, max_body_bytes: 262144, dedupe_days: 7 }],
}
export const spec = {
  ...model, providers: { enabled: true }, events: { enabled: true }, jobs: { enabled: true, jobs: [{ name: 'webhook_delivery' }] },
}
export type Block = 'notifications' | 'webhooks'
export const blocks = { notifications, webhooks }
export const blockReply = (name: Block, content: unknown, version = 3) => ({
  [name]: content, project_id: projectId, version, row_version: version, updated_at: version ? time : null,
})
