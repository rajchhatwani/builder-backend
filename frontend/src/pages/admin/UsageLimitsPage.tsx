import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { AdminOrg, OrgUsageMetric } from '../../api/types'
import { useUi } from '../../components/Ui'
import { Field, LoadFailed } from '../../shell/behavior/ui'

const errText = (e: unknown, fb: string) => (e instanceof Error ? e.message : fb)
const periodText = (m: OrgUsageMetric) => (m.period === 'none' ? 'Total' : m.period === 'day' ? 'Per day' : 'Per month')

/** Parses the limit box: empty = unlimited (null), otherwise a whole number of 0 or more. */
export function parseLimit(text: string): { value: number | null } | { error: string } {
  const t = text.trim()
  if (t === '') return { value: null }
  if (!/^-?\d+$/.test(t)) return { error: 'Enter a whole number, or leave empty for unlimited.' }
  const n = Number(t)
  if (n < 0) return { error: 'The limit cannot be negative.' }
  if (!Number.isSafeInteger(n)) return { error: 'That number is too large.' }
  return { value: n }
}

function MetricRow({ org, m, readOnly, onSaved }: { org: string; m: OrgUsageMetric; readOnly: boolean; onSaved: (metrics: OrgUsageMetric[]) => void }) {
  const { confirm, toast } = useUi()
  const [draft, setDraft] = useState(m.limit === null ? '' : String(m.limit))
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])
  useEffect(() => { setDraft(m.limit === null ? '' : String(m.limit)) }, [m.limit])
  const parsed = parseLimit(draft)
  const dirty = 'value' in parsed ? parsed.value !== m.limit : true

  async function save() {
    setError('')
    if ('error' in parsed) { setError(parsed.error); return }
    const to = parsed.value === null ? 'unlimited' : String(parsed.value)
    const ok = await confirm({
      title: `Change the ${m.metric} limit?`,
      message: `This organization's limit goes from ${m.limit === null ? 'unlimited' : m.limit} to ${to}. It takes effect right away${parsed.value !== null && m.used > parsed.value ? ', and current usage is already above it, so new work is refused' : ''}.`,
      confirmLabel: 'Change limit',
      danger: parsed.value !== null && m.used > parsed.value,
    })
    if (!ok) return
    setSaving(true)
    try {
      const r = await api.adminSetOrgUsageLimit(org, m.metric, parsed.value)
      if (!alive.current) return
      onSaved(r.metrics)
      toast(`Limit for ${m.metric} saved.`, 'success')
    } catch (e) {
      if (!alive.current) return
      setError(
        e instanceof ApiError && e.status === 403 ? 'Only platform admins can change usage limits.'
          : e instanceof ApiError && e.status === 404 ? 'This organization no longer exists.'
          : e instanceof ApiError && e.status === 400 ? `Unknown metric: ${m.metric}.`
          : errText(e, 'Could not save the limit'),
      )
    } finally {
      if (alive.current) setSaving(false)
    }
  }

  const id = `ul-${m.metric}`
  return (
    <tr data-testid="metric-row" data-metric={m.metric}>
      <th scope="row">{m.metric}</th>
      <td>{periodText(m)}</td>
      <td data-testid="metric-used">{m.used} {m.unit}</td>
      <td data-testid="metric-refused">{m.refused}</td>
      <td>
        <Field id={id} label={`Limit for ${m.metric} (${m.unit})`} messages={error ? [error] : undefined} hint={readOnly ? undefined : 'Empty means unlimited.'}>
          {(p) => (
            <input {...p} type="text" inputMode="numeric" disabled={readOnly || saving} placeholder="unlimited" value={draft}
              onChange={(e) => { setDraft(e.target.value); setError('') }} />
          )}
        </Field>
      </td>
      <td>
        {!readOnly && <button className="small" data-testid="metric-save" onClick={() => void save()} disabled={saving || !dirty}>{saving ? 'Saving…' : 'Save'}<span className="sr-only"> {m.metric}</span></button>}
      </td>
    </tr>
  )
}

/** Admin page "Usage limits": per-organization usage with editable limits. Reading: platform staff; editing: platform admins. */
export function UsageLimitsPage({ readOnly }: { readOnly: boolean }) {
  const [orgs, setOrgs] = useState<AdminOrg[]>([])
  const [pick, setPick] = useState('')
  const [org, setOrg] = useState<string | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [err, setErr] = useState('')
  const [metrics, setMetrics] = useState<OrgUsageMetric[]>([])
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])
  useEffect(() => {
    api.adminOrganizations('', 50, 0).then((p) => alive.current && setOrgs(p.items)).catch(() => undefined)
  }, [])

  const load = useCallback((o: string) => {
    setState('loading')
    api.adminOrgUsage(o).then((u) => {
      if (!alive.current) return
      setMetrics(u.metrics)
      setState('ready')
    }).catch((e) => {
      if (!alive.current) return
      setErr(e instanceof ApiError && e.status === 404 ? 'No organization with that id or slug.' : errText(e, 'Could not load'))
      setState('error')
    })
  }, [])

  function open() {
    const v = pick.trim()
    if (!v) return
    setOrg(v)
    load(v)
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Usage limits</h1>
          <p>Pick an organization to see what it used and change its limits.{readOnly && ' You can read these; only platform admins can change them.'}</p>
        </div>
      </div>
      <section className="card" aria-labelledby="ul-pick-title">
        <h2 id="ul-pick-title" className="sr-only">Organization</h2>
        <div className="bh-actions">
          <label htmlFor="ul-org" className="sr-only">Organization</label>
          <select id="ul-org" value={orgs.some((o) => o.id === pick) ? pick : ''} onChange={(e) => setPick(e.target.value)}>
            <option value="">Choose an organization…</option>
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <label htmlFor="ul-org-id" className="sr-only">Or organization id or slug</label>
          <input id="ul-org-id" type="text" placeholder="or paste an id or slug" value={pick} onChange={(e) => setPick(e.target.value)} />
          <button onClick={open} disabled={!pick.trim()} data-testid="ul-open">Show usage</button>
        </div>
      </section>
      {state === 'idle' && <p className="empty-state" data-testid="ul-idle">No organization selected.</p>}
      {state === 'loading' && <p className="empty-state" role="status">Loading…</p>}
      {state === 'error' && org && <LoadFailed what="this organization's usage" message={err} onRetry={() => load(org)} />}
      {state === 'ready' && org && (
        metrics.length === 0 ? <p className="empty-state" data-testid="ul-empty">This organization has no metered usage.</p> : (
          <section className="card" aria-labelledby="ul-table-title">
            <h2 id="ul-table-title" className="sr-only">Usage</h2>
            <table data-testid="usage-table">
              <caption className="sr-only">Usage and limits</caption>
              <thead><tr><th scope="col">Metric</th><th scope="col">Period</th><th scope="col">Used</th><th scope="col">Refused</th><th scope="col">Limit</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {metrics.map((m) => <MetricRow key={m.metric} org={org} m={m} readOnly={readOnly} onSaved={setMetrics} />)}
              </tbody>
            </table>
          </section>
        )
      )}
    </>
  )
}
