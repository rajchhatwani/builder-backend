import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Organization, OrgUsageMetric } from '../api/types'

const msg = (e: unknown) => (e instanceof Error ? e.message : "Can't reach the server.")

/** `#/org/<slug>/usage`: what each metered feature used, its limit and what was refused. Owners edit the limits. */
export function OrgUsageTab({ org }: { org: Organization }) {
  const isOwner = org.my_role === 'owner'
  const [metrics, setMetrics] = useState<OrgUsageMetric[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [edits, setEdits] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    try { setMetrics((await api.orgUsage(org.slug)).metrics); setError(null) } catch (e) { setError(msg(e)) }
  }, [org.slug])
  useEffect(() => { void load() }, [load])

  const setLimit = async (metric: string, value: number | null) => {
    setBusy(true); setError(null)
    try {
      setMetrics((await api.setOrgUsageLimit(org.slug, metric, value)).metrics)
      setEdits((e) => { const { [metric]: _drop, ...rest } = e; return rest })
    } catch (e) { setError(msg(e)) } finally { setBusy(false) }
  }

  return (
    <>
      {error && <p role="alert" data-testid="usage-error">{error}</p>}
      {metrics === null && !error && <p className="empty-state">Loading…</p>}
      {metrics && metrics.length === 0 && <p className="empty-state" data-testid="usage-empty">Nothing is metered yet.</p>}
      {metrics && metrics.length > 0 && (
        <div className="table">
          <table aria-label="Usage" data-testid="usage-table">
            <thead><tr><th>Metric</th><th>Period</th><th>Used</th><th>Limit</th><th>Refused</th>{isOwner && <th>Change limit</th>}</tr></thead>
            <tbody>
              {metrics.map((m) => {
                const near = m.limit !== null && m.limit > 0 && m.used >= m.limit * 0.9
                return (
                  <tr key={m.metric} data-testid="usage-row" data-metric={m.metric} data-near-limit={near}>
                    <td>{m.metric} <small className="muted">({m.unit})</small></td>
                    <td>{m.period}</td>
                    <td data-testid="usage-used">{m.used}</td>
                    <td data-testid="usage-limit">{m.limit === null ? 'No limit' : m.limit}</td>
                    <td data-testid="usage-refused">{m.refused}</td>
                    {isOwner && (
                      <td>
                        <input type="number" min={0} aria-label={`New limit for ${m.metric}`} value={edits[m.metric] ?? ''} onChange={(e) => setEdits((cur) => ({ ...cur, [m.metric]: e.target.value }))} data-testid="usage-edit" />{' '}
                        <button className="small" disabled={busy || (edits[m.metric] ?? '') === '' || Number(edits[m.metric]) < 0} onClick={() => void setLimit(m.metric, Math.floor(Number(edits[m.metric])))} data-testid="usage-save" aria-label={`Save limit for ${m.metric}`}>Save</button>{' '}
                        <button className="outline small" disabled={busy || m.limit === null} onClick={() => void setLimit(m.metric, null)} data-testid="usage-clear" aria-label={`Remove limit for ${m.metric}`}>No limit</button>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
