import { useCallback, useEffect, useId, useState } from 'react'
import { api } from '../api/client'
import type { Organization, OrgAiCost, OrgAiSettings } from '../api/types'

export const usd = (micro: number): string => `$${(micro / 1_000_000).toFixed(2)}`
const msg = (e: unknown) => (e instanceof Error ? e.message : "Can't reach the server.")

/** `#/org/<slug>/ai`: the organization's own AI key, monthly budget and spend. Admins and owners only. */
export function OrgAiTab({ org }: { org: Organization }) {
  const canAdmin = org.my_role === 'owner' || org.my_role === 'admin'
  const [settings, setSettings] = useState<OrgAiSettings | null>(null)
  const [cost, setCost] = useState<OrgAiCost | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [key, setKey] = useState('')
  const [budget, setBudget] = useState('')
  const keyId = useId()
  const budgetId = useId()

  const adopt = (s: OrgAiSettings) => { setSettings(s); setBudget(s.monthly_budget_micro_usd === null ? '' : String(s.monthly_budget_micro_usd / 1_000_000)) }
  const load = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([api.orgAiSettings(org.slug), api.orgAiCost(org.slug)])
      adopt(s); setCost(c); setError(null)
    } catch (e) { setError(msg(e)) }
  }, [org.slug])
  useEffect(() => { if (canAdmin) void load() }, [canAdmin, load])

  const save = async (body: Parameters<typeof api.updateOrgAiSettings>[1]) => {
    setBusy(true); setError(null); setSaved(false)
    try { adopt(await api.updateOrgAiSettings(org.slug, body)); setKey(''); setSaved(true); setCost(await api.orgAiCost(org.slug)) } catch (e) { setError(msg(e)) } finally { setBusy(false) }
  }
  const submit = () => {
    const body: Parameters<typeof api.updateOrgAiSettings>[1] = {}
    if (key.trim()) body.api_key = key.trim()
    const n = Number(budget)
    if (budget.trim() !== '' && Number.isFinite(n) && n >= 0 && Math.round(n * 1_000_000) !== settings?.monthly_budget_micro_usd) body.monthly_budget_micro_usd = Math.round(n * 1_000_000)
    if (Object.keys(body).length > 0) void save(body)
  }

  if (!canAdmin) return <p className="empty-state" role="alert" data-testid="ai-noaccess">AI settings are for organization admins and owners.</p>
  return (
    <>
      {error && <p role="alert" data-testid="ai-error">{error}</p>}
      {saved && <p role="status" data-testid="ai-saved">Saved.</p>}
      {settings && (
        <form className="card" aria-label="AI settings" onSubmit={(e) => { e.preventDefault(); submit() }}>
          <h2>AI settings</h2>
          <p data-testid="ai-key-state">{settings.has_api_key ? `Your own provider key is in use (${settings.api_key_hint ?? 'hidden'}).` : 'No key of your own: the platform key is used.'}</p>
          <div className="field">
            <label htmlFor={keyId}>New provider API key</label>
            <input id={keyId} type="password" autoComplete="off" value={key} maxLength={300} placeholder="sk-…" onChange={(e) => setKey(e.target.value)} data-testid="ai-key" />
          </div>
          <div className="field">
            <label htmlFor={budgetId}>Monthly budget (USD)</label>
            <input id={budgetId} type="number" min={0} step="0.01" value={budget} onChange={(e) => setBudget(e.target.value)} data-testid="ai-budget" />
          </div>
          <div className="row">
            <button type="submit" disabled={busy} data-testid="ai-save">Save</button>
            {settings.has_api_key && <button type="button" className="outline" disabled={busy} onClick={() => void save({ clear_api_key: true })} data-testid="ai-clear-key">Remove my key</button>}
            {settings.monthly_budget_micro_usd !== null && <button type="button" className="outline" disabled={busy} onClick={() => void save({ clear_budget: true })} data-testid="ai-clear-budget">Remove the budget</button>}
          </div>
        </form>
      )}
      {cost && (
        <section className="card" aria-labelledby="ai-cost-h" data-testid="ai-cost">
          <h2 id="ai-cost-h">Spend</h2>
          <p data-testid="ai-cost-month">This month: {usd(cost.month_cost_micro_usd)}{cost.monthly_budget_micro_usd !== null ? ` of ${usd(cost.monthly_budget_micro_usd)}` : ''}. All time: {usd(cost.total_cost_micro_usd)}.</p>
          {cost.items.length === 0 ? <p className="empty-state">No AI calls recorded yet.</p> : (
            <div className="table">
              <table aria-label="AI cost ledger">
                <thead><tr><th>When</th><th>Model</th><th>Task</th><th>Tokens in/out</th><th>Cost</th></tr></thead>
                <tbody>
                  {cost.items.map((r) => (
                    <tr key={r.id} data-testid="ai-cost-row"><td>{r.created_at.slice(0, 16).replace('T', ' ')}</td><td>{r.model}</td><td>{r.task_class}</td><td>{r.input_tokens} / {r.output_tokens}</td><td>{usd(r.cost_micro_usd)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {cost.total > cost.items.length && <p className="muted small-text">Showing the latest {cost.items.length} of {cost.total} calls.</p>}
        </section>
      )}
    </>
  )
}
