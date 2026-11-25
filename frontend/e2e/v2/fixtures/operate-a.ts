import { model, projectId, time } from './connect-a'

export const jobSettings = {
  enabled: true, queue: { backend: 'postgres' },
  jobs: [{ name: 'send_invoice', queue: 'default', handler: 'send_invoice', timeout_seconds: 300,
    retry: { max_attempts: 3, backoff_seconds: 30, backoff: 'exponential' } }],
  worker_groups: [{ name: 'billing', concurrency: 4, queues: ['default'], placement: 'same_server' }],
  schedules: [{ name: 'weekly_billing', job: 'send_invoice', cron: '0 8 * * 1', timezone: 'UTC', enabled: true, missed: 'catch_up_one' }],
}
export const workflowSettings = {
  enabled: true, runtime: 'postgres', worker: { concurrency: 2 },
  workflows: [{ name: 'approve_invoice', roles: ['employee'], on_failure: 'compensate', timeout_seconds: 3600,
    steps: [{ name: 'send_invoice', kind: 'job', job: 'send_invoice', compensate: true, timeout_seconds: 60,
      retry: { max_attempts: 3, backoff_seconds: 5, backoff: 'exponential' } }] }],
}
export const operateSpec = { ...model, jobs: jobSettings, workflows: workflowSettings }
export const observation = {
  project_id: projectId, enabled: true, service_name: 'billing', sample_ratio: .1, metrics: true, db_spans: true,
  exclude_paths: ['/health', '/ready'], extra_redact_keys: ['card_number'], local_stack: true, expected_rps: 250,
  version: 3, updated_at: time, recommended_sample_ratio: .2, default_service_name: 'billing',
  redacted_keys: ['password', 'secret', 'token', 'authorization'],
}
export const metric = {
  key: 'total_paid', version: 2, updated_at: time,
  definition: { key: 'total_paid', label: 'Total paid', entity: 'Invoice', agg: 'sum', field: 'amount', group_by: 'payment_status',
    filter: [{ field: 'payment_status', op: 'eq', value: 'paid' }], unit: 'USD' },
}
export const metricValue = { key: metric.key, version: 2, computed_at: time, value: null, groups: [{ key: 'paid', value: '600.6' }] }
export const report = { id: 'e05a9f8d-e17d-4737-80a9-9288283c46aa', name: 'Daily billing', metric_keys: [metric.key],
  enabled: true, timezone: 'UTC', schedule: '0 8 * * *', updated_at: time, last_scheduled_for: time }
export const reportRun = { id: 'run', report_id: report.id, status: 'ok', scheduled_for: time, created_at: time,
  values: { [metric.key]: { value: null, groups: metricValue.groups } } }
export const hits = { hits: [{ id: 'inv-007', payment_status: 'paid', amount: '600.6' }], entity: 'Invoice', as_role: 'employee', adapter: 'fts', total: 1 }
export const advisor = {
  queue: { recommended: 'postgres', reasons: ['The database already runs alongside the app.'], warnings: [], upgrade_path: ['Scale the workers first.'] },
  workflow: { recommended: 'queue', reasons: ['A single job fits the request.'], warnings: [], implemented: true,
    next_step: 'Declare a job in the jobs block.' },
}
