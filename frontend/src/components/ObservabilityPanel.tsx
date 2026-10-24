import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ObservabilitySettings, ValidationIssue } from '../api/types'
import { useUi } from './Ui'

interface Form {
  enabled: boolean
  serviceName: string
  sampleRatio: string
  metrics: boolean
  dbSpans: boolean
  excludePaths: string
  extraRedactKeys: string
  localStack: boolean
  expectedRps: string
}

function toForm(s: ObservabilitySettings): Form {
  return {
    enabled: s.enabled,
    serviceName: s.service_name ?? '',
    sampleRatio: String(s.sample_ratio),
    metrics: s.metrics,
    dbSpans: s.db_spans,
    excludePaths: s.exclude_paths.join('\n'),
    extraRedactKeys: s.extra_redact_keys.join('\n'),
    localStack: s.local_stack,
    expectedRps: s.expected_rps === null ? '' : String(s.expected_rps),
  }
}

const lines = (text: string) =>
  text
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l !== '')

const COLLECTED: { what: string; how: string }[] = [
  { what: 'One server span per request, named after the route', how: 'FastAPI instrumentation' },
  { what: 'One span per SQL statement (placeholders, never the values)', how: 'asyncpg instrumentation' },
  { what: 'Request count and duration per route and status code', how: 'FastAPI instrumentation' },
  { what: 'A counter of requests refused by a policy (ABAC / PBAC)', how: 'generated code' },
  { what: 'JSON logs carrying trace_id, span_id and request_id', how: 'structlog' },
]

/** OpenTelemetry for the generated service: what is collected, how much, and what is kept out. */
export function ObservabilityPanel({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const { toast } = useUi()
  const [settings, setSettings] = useState<ObservabilitySettings | null>(null)
  const [form, setForm] = useState<Form | null>(null)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const [s, i] = await Promise.all([api.getObservability(projectId), api.observabilityIssues(projectId)])
      setSettings(s)
      setForm(toForm(s))
      setIssues(i.issues)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the observability settings.')
    }
  }, [projectId])

  useEffect(() => {
    load()
  }, [load])

  if (error && !settings) {
    return (
      <div role="alert" data-variant="danger">
        {error}
      </div>
    )
  }
  if (!settings || !form) return <p className="empty-state">Loading…</p>

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm({ ...form, [key]: value })

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!form || !settings) return
    setSaving(true)
    setError(null)
    try {
      const saved = await api.putObservability(projectId, {
        enabled: form.enabled,
        service_name: form.serviceName.trim() === '' ? null : form.serviceName.trim(),
        sample_ratio: Number(form.sampleRatio),
        metrics: form.metrics,
        db_spans: form.dbSpans,
        exclude_paths: lines(form.excludePaths),
        extra_redact_keys: lines(form.extraRedactKeys),
        local_stack: form.localStack,
        expected_rps: form.expectedRps.trim() === '' ? null : Number(form.expectedRps),
        expected_version: settings.version,
      })
      setSettings(saved)
      setForm(toForm(saved))
      setIssues((await api.observabilityIssues(projectId)).issues)
      onChanged()
      toast('Observability settings saved.')
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        await load()
        setError('Someone else changed these settings. They were reloaded: apply your change again.')
      } else {
        setError(err instanceof Error ? err.message : 'Could not save.')
      }
    } finally {
      setSaving(false)
    }
  }

  const ratio = Number(form.sampleRatio)
  const rps = form.expectedRps.trim() === '' ? null : Number(form.expectedRps)
  const never = settings.version === 0

  return (
    <>
      {issues.length > 0 && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-4)' }}>
          <strong>
            {issues.length} problem{issues.length === 1 ? '' : 's'} to fix before you can generate
          </strong>
          <ul className="issue-list">
            {issues.map((issue, i) => (
              <li key={i}>
                <span>
                  {issue.message}
                  <small className="muted"> · {issue.path.replace('observability.', '')}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form className="card" onSubmit={save}>
        {error && (
          <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
            {error}
          </div>
        )}
        <div className="toggle-field">
          <label>
            <input type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} />
            <span>
              <strong>Add OpenTelemetry to the generated backend</strong>
              <br />
              <span className="muted small-text">
                {never
                  ? 'Off until you save. The next download then includes tracing, metrics and a local collector.'
                  : 'Turn off to stop generating it. Nothing already deployed is changed.'}
              </span>
            </span>
          </label>
        </div>

        <details open className="auth-section">
          <summary>What is collected</summary>
          <div className="auth-section-body">
            <ul>
              {COLLECTED.map((c) => (
                <li key={c.what}>
                  {c.what} <span className="muted small-text">({c.how})</span>
                </li>
              ))}
            </ul>
            <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <input type="checkbox" checked={form.metrics} onChange={(e) => set('metrics', e.target.checked)} />
              Metrics (request counts and durations)
            </label>
            <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <input type="checkbox" checked={form.dbSpans} onChange={(e) => set('dbSpans', e.target.checked)} />
              One span per database statement
            </label>
            <p className="muted small-text">
              Never collected: request or response bodies, headers, cookies, or SQL parameter values. Logs stay JSON on stdout; they are
              not exported over OTLP (ship them with your platform’s log collector; they correlate by trace id).
            </p>
          </div>
        </details>

        <details open className="auth-section">
          <summary>How much</summary>
          <div className="auth-section-body">
            <div className="field-grid">
              <label>
                Service name (blank: “{settings.default_service_name}”)
                <input value={form.serviceName} onChange={(e) => set('serviceName', e.target.value)} placeholder={settings.default_service_name} />
              </label>
              <label>
                Share of traces kept (0 to 1)
                <input type="number" min={0} max={1} step={0.01} value={form.sampleRatio} onChange={(e) => set('sampleRatio', e.target.value)} />
              </label>
              <label>
                Peak requests per second (optional)
                <input type="number" min={1} value={form.expectedRps} placeholder="for the advice below" onChange={(e) => set('expectedRps', e.target.value)} />
              </label>
            </div>
            <p className="muted small-text">
              {rps !== null && rps > 0 ? (
                <>
                  At about {rps} requests per second, keeping <strong>{settings.recommended_sample_ratio}</strong> of traces holds a small
                  collector near 200 spans per second (rule of thumb: 4 spans per request).{' '}
                  {Number.isFinite(ratio) && ratio > settings.recommended_sample_ratio && (
                    <strong>Your setting of {ratio} is higher than that.</strong>
                  )}
                </>
              ) : (
                'Enter your expected peak requests per second to get a suggested share. Metrics are cheap and are never sampled. The share can be changed later with an environment variable, without redeploying code.'
              )}
            </p>
            <label>
              Paths that never produce traces (one per line)
              <textarea rows={3} value={form.excludePaths} onChange={(e) => set('excludePaths', e.target.value)} />
            </label>
          </div>
        </details>

        <details open className="auth-section">
          <summary>What is kept out</summary>
          <div className="auth-section-body">
            <p className="muted small-text">
              Built in: values stored under a key containing {settings.redacted_keys.join(', ')} are hidden, as are JWTs, bearer tokens,
              provider keys and passwords inside URLs, and every query-string value. A collector repeats the masking.
            </p>
            <label>
              Extra key names to hide (one per line, lower case)
              <textarea rows={3} value={form.extraRedactKeys} placeholder={'ssn\nnric'} onChange={(e) => set('extraRedactKeys', e.target.value)} />
            </label>
            <p className="muted small-text">This list can only add to the built-in one.</p>
          </div>
        </details>

        <details open className="auth-section">
          <summary>Local development stack</summary>
          <div className="auth-section-body">
            <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <input type="checkbox" checked={form.localStack} onChange={(e) => set('localStack', e.target.checked)} />
              Include a collector, Jaeger (traces) and Prometheus (metrics) as <code>deploy/observability/</code>
            </label>
            <p className="muted small-text">
              Start with <code>docker compose -f docker-compose.yml -f deploy/observability/compose.yml up</code>. For production, point
              <code> OTEL_EXPORTER_OTLP_ENDPOINT</code> at your own collector or hosted backend; the endpoint and any credentials are
              environment variables and are never stored here.
            </p>
          </div>
        </details>

        <div style={{ marginBlockStart: 'var(--space-4)' }}>
          <button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </>
  )
}
