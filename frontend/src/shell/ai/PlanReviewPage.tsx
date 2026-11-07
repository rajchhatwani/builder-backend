import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../../api/client'
import { aiApi } from './aiApi'
import { PLAN_ERRORS, PLAN_KEYS, PLAN_LABEL, addRow, editedInfo, gateAFor, isEdited, phasesOf, planBody, planRows, toggleRow, type PlanKey, type PlanRow } from './planLogic'
import type { Approval } from './types'
import { errMsg, runLink, useRunParam } from './useRunParam'

/** F3-2: Gate A. What the agent wants to touch, as a table you can trim; approve, deny, or send your changes back. */
export function PlanReviewPage({ projectId }: { projectId: string }) {
  const runId = useRunParam()
  const [approval, setApproval] = useState<Approval | null>(null)
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<PlanRow[]>([])
  const [note, setNote] = useState('')
  const [addKey, setAddKey] = useState<PlanKey>('entities')
  const [addValue, setAddValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')

  const load = useCallback(async () => {
    try {
      // with a run in the link also the decided plan is shown (with what the reviewer changed)
      const list = await aiApi.listApprovals(projectId, runId ? { run_id: runId } : { state: 'pending' })
      const a = gateAFor(list)
      setApproval(a)
      setRows(a ? planRows(a.payload) : [])
    } catch (e) { setError(errMsg(e)) } finally { setLoading(false) }
  }, [projectId, runId])
  useEffect(() => { void load() }, [load])

  const original = useMemo(() => (approval ? planRows(approval.payload) : []), [approval])
  const edited = isEdited(rows, original)
  const open = approval?.state === 'pending'
  const was = approval && !open ? editedInfo(approval.payload) : null

  const decide = async (approve: boolean, text?: string, msg = '', plan?: Record<string, string[]>) => {
    if (!approval) return
    setBusy(true); setError('')
    try {
      await aiApi.decide(projectId, approval.id, approve, text, plan)
      setDone(msg)
      setApproval(null)
    } catch (e) { setError(e instanceof ApiError && PLAN_ERRORS[e.code] ? PLAN_ERRORS[e.code] : errMsg(e)) } finally { setBusy(false) }
  }

  return (
    <section data-testid="plan-page">
      <h1>Review the plan</h1>
      <p className="muted">Before it builds, the agent tells you what it plans to touch. Nothing outside this list can be changed.</p>
      {error && <p className="bh-error" role="alert">{error}</p>}
      {loading && <p className="empty-state">Loading…</p>}
      {done && (
        <p data-testid="plan-done">{done} {runId && <a href={runLink(projectId, 'build', runId)}>Back to the build</a>}</p>
      )}
      {!loading && !approval && !done && (
        <p className="empty-state" data-testid="plan-empty">No plan is waiting for your approval.</p>
      )}

      {approval && (
        <div className="card" data-testid="plan-card">
          <h2>{approval.subject}</h2>
          {!open && (
            <p className="card" role="status" data-testid="plan-state" data-state={approval.state}>
              <strong>{approval.state === 'approved' ? 'Approved' : approval.state === 'denied' ? 'Denied' : approval.state === 'superseded' ? 'Replaced by a newer plan' : 'Expired'}.</strong>
              {approval.decision_note && <> Note: {approval.decision_note}</>}
            </p>
          )}
          {was && (
            <div data-testid="plan-edited-from">
              <h3>Edited by a reviewer</h3>
              <p className="muted small-text">Edited by {was.by ?? (approval.decided_by ? `user ${approval.decided_by.slice(0, 8)}` : 'a reviewer')}. The plan below is what was approved; the agent had proposed this:</p>
              <ul className="ai-files">{was.from.map((r) => <li key={`${r.key}-${r.value}`}>{PLAN_LABEL[r.key]}: <code>{r.value}</code></li>)}</ul>
            </div>
          )}
          {approval.requires_owner && <p className="badge">Only a project owner can decide this</p>}
          {approval.risk_flags.length > 0 && (
            <p data-testid="plan-risks">{approval.risk_flags.map((f) => <span key={f} className="badge badge-muted">{f}</span>)}</p>
          )}
          {phasesOf(approval.payload).length > 0 && (
            <ol className="ai-phases" data-testid="plan-phases">{phasesOf(approval.payload).map((p, i) => <li key={`${i}-${p}`}>{p}</li>)}</ol>
          )}
          <table data-testid="plan-table">
            <thead><tr><th>Kind</th><th>It may touch</th><th /></tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={3} className="muted">Nothing listed: the build step could touch nothing.</td></tr>}
              {rows.map((r, i) => (
                <tr key={`${r.key}-${r.value}`} data-removed={r.removed || undefined}>
                  <td>{PLAN_LABEL[r.key]}</td>
                  <td className={r.removed ? 'ai-struck' : undefined}><code>{r.value}</code></td>
                  <td>{open && <button className="small outline" onClick={() => setRows(toggleRow(rows, i))}>{r.removed ? 'Keep' : 'Remove'}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {open && (
            <>
              <div className="hstack">
                <select aria-label="Kind to add" value={addKey} onChange={(e) => setAddKey(e.target.value as PlanKey)}>
                  {PLAN_KEYS.map((k) => <option key={k} value={k}>{PLAN_LABEL[k]}</option>)}
                </select>
                <input aria-label="Name to add" value={addValue} maxLength={120} onChange={(e) => setAddValue(e.target.value)} />
                <button className="small outline" disabled={!addValue.trim()} onClick={() => { setRows(addRow(rows, addKey, addValue)); setAddValue('') }}>Add</button>
              </div>
              <label htmlFor="plan-note">Note (optional)</label>
              <input id="plan-note" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
              {edited && <p className="muted small-text" data-testid="plan-edited">You changed the scope. Approving sends your list: the build step is then limited to exactly what is left. The agent's original is kept on record.</p>}
              <div className="hstack">
                <button disabled={busy} onClick={() => void decide(true, note, edited ? 'Your edited plan was approved.' : 'Plan approved.', edited ? planBody(rows) : undefined)} data-testid="plan-approve">{edited ? 'Approve my edited plan' : 'Approve plan'}</button>
                <button className="outline" disabled={busy} onClick={() => void decide(false, note, 'Plan denied.')} data-testid="plan-deny">Deny</button>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}
