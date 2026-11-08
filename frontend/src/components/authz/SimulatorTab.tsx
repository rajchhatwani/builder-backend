import { useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { SimulateResult } from '../../api/types'
import { OPERATIONS, type Catalogue } from './policyModel'

/** Asks the saved policies "would this be allowed?" with a made-up person, record and moment. */
export function SimulatorTab({ projectId, catalogue }: { projectId: string; catalogue: Catalogue }) {
  const [entity, setEntity] = useState(catalogue.entities[0]?.name ?? '')
  const [op, setOp] = useState<string>('get')
  const [roles, setRoles] = useState<string[]>([])
  const [subjectId, setSubjectId] = useState('11111111-1111-1111-1111-111111111111')
  const [email, setEmail] = useState('someone@example.com')
  const [tenantId, setTenantId] = useState('')
  const [record, setRecord] = useState('{\n  "status": "draft"\n}')
  const [hour, setHour] = useState('')
  const [weekday, setWeekday] = useState('')
  const [ip, setIp] = useState('')
  const [result, setResult] = useState<SimulateResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const entityInfo = catalogue.entities.find((e) => e.name === entity)
  const attributes = Object.entries(catalogue.resource[entity] ?? {})
  const multiTenant = 'tenant_id' in catalogue.subject

  async function run(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setResult(null)
    let resource: Record<string, unknown> | null = null
    if (record.trim() !== '') {
      try {
        const parsed: unknown = JSON.parse(record)
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('not an object')
        resource = parsed as Record<string, unknown>
      } catch {
        setError('The record must be a JSON object such as {"status": "draft"}.')
        return
      }
    }
    const subject: Record<string, unknown> = { id: subjectId, email, roles }
    if (multiTenant && tenantId) subject.tenant_id = tenantId
    const env: Record<string, unknown> = {}
    if (hour !== '') env.hour_utc = Number(hour)
    if (weekday !== '') env.weekday_utc = Number(weekday)
    if (ip !== '') env.client_ip = ip
    setBusy(true)
    try {
      setResult(await api.simulateAuthorization(projectId, { entity, op, subject, resource, env }))
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : 'The simulation failed.')
    } finally {
      setBusy(false)
    }
  }

  if (catalogue.entities.length === 0) {
    return <p className="empty-state">Add an entity in the data model first.</p>
  }

  return (
    <div className="card">
      <p className="muted small-text">
        Uses the saved policies and the same engine as the generated backend, so the answer is what your API will do.
        For <em>create</em>, the record is the data being sent. Fields you leave out count as empty.
      </p>
      <form onSubmit={run}>
        <div className="field-grid">
          <label>
            Entity
            <select
              value={entity}
              onChange={(e) => {
                setEntity(e.target.value)
                setResult(null)
              }}
            >
              {catalogue.entities.map((e) => (
                <option key={e.name} value={e.name}>
                  {e.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Action
            <select value={op} onChange={(e) => setOp(e.target.value)}>
              {OPERATIONS.filter((o) => entityInfo?.ops.includes(o)).map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
        </div>

        <fieldset style={{ border: 0, padding: 0, marginBlockStart: 'var(--space-3)' }}>
          <legend>Who is asking</legend>
          <div style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
            {catalogue.roles.length === 0 && <span className="muted small-text">No roles are defined.</span>}
            {catalogue.roles.map((r) => (
              <label key={r} style={{ display: 'inline-flex', gap: 'var(--space-1)', margin: 0 }}>
                <input
                  type="checkbox"
                  checked={roles.includes(r)}
                  onChange={(e) => setRoles(e.target.checked ? [...roles, r] : roles.filter((x) => x !== r))}
                />
                {r}
              </label>
            ))}
          </div>
          <div className="field-grid" style={{ marginBlockStart: 'var(--space-2)' }}>
            <label>
              Person id
              <input value={subjectId} onChange={(e) => setSubjectId(e.target.value)} />
            </label>
            <label>
              E-mail
              <input value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            {multiTenant && (
              <label>
                Organisation id
                <input value={tenantId} onChange={(e) => setTenantId(e.target.value)} />
              </label>
            )}
          </div>
        </fieldset>

        <label style={{ marginBlockStart: 'var(--space-3)' }}>
          The record (JSON){' '}
          <span className="muted small-text">
            {attributes.map(([name, kind]) => `${name}: ${kind}`).join(' · ')}
          </span>
          <textarea rows={5} value={record} spellCheck={false} onChange={(e) => setRecord(e.target.value)} />
        </label>

        <fieldset style={{ border: 0, padding: 0, marginBlockStart: 'var(--space-3)' }}>
          <legend>The moment (optional)</legend>
          <div className="field-grid">
            <label>
              Hour (UTC, 0-23)
              <input type="number" min={0} max={23} value={hour} onChange={(e) => setHour(e.target.value)} />
            </label>
            <label>
              Weekday (0 = Monday)
              <input type="number" min={0} max={6} value={weekday} onChange={(e) => setWeekday(e.target.value)} />
            </label>
            <label>
              Caller IP
              <input value={ip} placeholder="203.0.113.7" onChange={(e) => setIp(e.target.value)} />
            </label>
          </div>
        </fieldset>

        <div style={{ marginBlockStart: 'var(--space-4)' }}>
          <button type="submit" disabled={busy}>
            {busy ? 'Deciding…' : 'Would this be allowed?'}
          </button>
        </div>
      </form>

      {error && (
        <div role="alert" data-variant="danger" style={{ marginBlockStart: 'var(--space-4)' }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{ marginBlockStart: 'var(--space-4)' }}>
          <div role="status" data-variant={result.allowed ? 'success' : 'danger'}>
            <strong>{result.allowed ? 'Allowed' : 'Denied'}</strong> — {result.reason}
          </div>
          {result.trace.length === 0 ? (
            <p className="muted small-text">No policy applies to this person for this action.</p>
          ) : (
            <ul className="issue-list" style={{ marginBlockStart: 'var(--space-3)' }}>
              {result.trace.map((t) => (
                <li key={t.policy} style={{ display: 'block' }}>
                  <strong>{t.policy}</strong> <span className="badge badge-outline">{t.effect}</span>{' '}
                  <span className="badge badge-muted">{t.condition_met ? 'condition met' : 'condition not met'}</span>
                  <div className="muted small-text">When: {t.condition}</div>
                  {t.leaves.length > 0 && (
                    <ul style={{ margin: 'var(--space-1) 0 0', paddingInlineStart: 'var(--space-5)' }}>
                      {t.leaves.map((l, i) => (
                        <li key={i} className="small-text" style={{ border: 0, padding: 0 }}>
                          {l.result ? '✓' : '✗'} {l.text}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
