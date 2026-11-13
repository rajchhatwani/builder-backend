import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { sendRequest } from '../workbench/sendRequest'
import { PREVIEW_ORIGIN } from '../workbench/previewOrigin'
import {
  OUTCOMES, OUTCOME_LABEL, STATUSES, STATUS_LABEL, approvalErrorMessage, argsText, canAcknowledge, canDecide, canHandOff, canMarkOutcome, canReject, moveRow, pageInfo,
  riskColors, riskLabel, successRate, type AgentStat, type Proposal, type Run,
} from './approvalLogic'

type Page<T> = { items: T[]; total?: number; limit?: number; offset?: number }
type Load<T> = { s: 'idle' } | { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: T }
const msg = (e: unknown, f: string) => (e instanceof Error ? e.message : f)
const LIMIT = 20

/** AI action approvals for a generated project's agents pack (D37): inbox of proposals, decide, record outcomes, per-agent stats.
 *  Bearer token held in memory only. The server enforces roles, autonomy and self-approval; every refusal is shown, never hidden. */
export function AgentApprovalsPage({ projectId, origin = PREVIEW_ORIGIN, doFetch = fetch }: { projectId: string; origin?: string | null; doFetch?: typeof fetch }) {
  const [token, setToken] = useState('')
  const [active, setActive] = useState('')
  const [status, setStatus] = useState('pending_approval')
  const [offset, setOffset] = useState(0)
  const [list, setList] = useState<Load<Page<Proposal>>>({ s: 'idle' })
  const [stats, setStats] = useState<Load<AgentStat[]>>({ s: 'idle' })
  const [refresh, setRefresh] = useState(0)
  const [rowFocus, setRowFocus] = useState(0)
  const [busy, setBusy] = useState(false)
  const [forms, setForms] = useState<{ id: string; kind: 'reject' | 'handoff' } | null>(null)
  const [text, setText] = useState('')
  const [runs, setRuns] = useState<Record<string, Run | string>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState<string | null>(null)
  const tokenId = useId(), statusId = useId(), textId = useId()
  const rowRefs = useRef(new Map<number, HTMLButtonElement>())

  const call = useCallback(async (method: string, path: string, body?: unknown) => {
    if (!origin) throw new Error('No preview API is configured')
    const r = await sendRequest({ url: origin + path, origin, method, body: body === undefined ? undefined : JSON.stringify(body), bearer: active || undefined }, doFetch)
    let json: unknown = null
    try { json = r.text ? JSON.parse(r.text) : null } catch { json = null }
    return { status: r.status, json }
  }, [origin, active, doFetch])

  useEffect(() => { setActive(''); setToken(''); setList({ s: 'idle' }); setStats({ s: 'idle' }); setErrors({}); setNotice(null); setOffset(0); setForms(null); setRuns({}) }, [projectId])

  useEffect(() => {
    if (!active) return
    let dead = false
    setList({ s: 'loading' })
    void (async () => {
      try {
        const r = await call('GET', `/ai/agents/proposals?status=${encodeURIComponent(status)}&limit=${LIMIT}&offset=${offset}`)
        if (dead) return
        if (r.status >= 200 && r.status < 300 && r.json && typeof r.json === 'object' && Array.isArray((r.json as Page<Proposal>).items)) setList({ s: 'ok', v: r.json as Page<Proposal> })
        else setList({ s: 'error', m: approvalErrorMessage(r.status, r.json) })
      } catch (e) { if (!dead) setList({ s: 'error', m: msg(e, 'Could not reach the agents API') }) }
    })()
    return () => { dead = true }
  }, [active, status, offset, refresh, call])

  useEffect(() => {
    if (!active) return
    let dead = false
    setStats({ s: 'loading' })
    void (async () => {
      try {
        const r = await call('GET', '/ai/agents/stats')
        if (dead) return
        const a = r.json && typeof r.json === 'object' ? (r.json as { agents?: unknown }).agents : null
        if (r.status >= 200 && r.status < 300 && Array.isArray(a)) setStats({ s: 'ok', v: a as AgentStat[] })
        else setStats({ s: 'error', m: approvalErrorMessage(r.status, r.json) })
      } catch (e) { if (!dead) setStats({ s: 'error', m: msg(e, 'Could not reach the agents API') }) }
    })()
    return () => { dead = true }
  }, [active, refresh, call])

  const items = list.s === 'ok' ? list.v.items : []
  const total = list.s === 'ok' ? list.v.total ?? items.length : 0
  const pg = pageInfo(total, LIMIT, offset)

  function onRowKey(e: React.KeyboardEvent, i: number) {
    if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return
    e.preventDefault()
    const n = moveRow(items.length, i, e.key)
    setRowFocus(n); rowRefs.current.get(n)?.focus()
  }

  async function act(p: Proposal, path: string, body: unknown, ok: string) {
    setBusy(true); setNotice(null); setErrors((m) => { const { [p.id]: _drop, ...rest } = m; return rest })
    try {
      const r = await call('POST', `/ai/agents/proposals/${encodeURIComponent(p.id)}/${path}`, body)
      if (r.status >= 200 && r.status < 300) {
        setNotice(`${p.action}: ${ok}`); setForms(null); setText(''); setRefresh((n) => n + 1)
      } else {
        setErrors((m) => ({ ...m, [p.id]: approvalErrorMessage(r.status, r.json) }))
        if (r.status === 409 || r.status === 404) setRefresh((n) => n + 1)
      }
    } catch (e) { setErrors((m) => ({ ...m, [p.id]: msg(e, 'Could not reach the agents API') })) } finally { setBusy(false) }
  }
  async function showRun(p: Proposal) {
    if (runs[p.run_id]) { setRuns((m) => { const { [p.run_id]: _drop, ...rest } = m; return rest }); return }
    try {
      const r = await call('GET', `/ai/agents/runs/${encodeURIComponent(p.run_id)}`)
      const ok = r.status >= 200 && r.status < 300 && r.json && typeof r.json === 'object'
      setRuns((m) => ({ ...m, [p.run_id]: ok ? (r.json as Run) : approvalErrorMessage(r.status, r.json) }))
    } catch (e) { setRuns((m) => ({ ...m, [p.run_id]: msg(e, 'Could not reach the agents API') })) }
  }

  if (!origin) {
    return (
      <section aria-labelledby="aa-h" data-testid="agentapprovals-page">
        <h1 id="aa-h">AI action approvals</h1>
        <p className="muted" data-testid="agentapprovals-no-origin">No preview API is configured for this dashboard, so there is no approval inbox to read yet (set <code>VITE_PREVIEW_API_ORIGIN</code> to a running generated project with the AI agents pack on).</p>
      </section>
    )
  }

  return (
    <section aria-labelledby="aa-h" data-testid="agentapprovals-page" className="stack">
      <h1 id="aa-h">AI action approvals</h1>
      <p className="muted">Actions your AI agents propose. Nothing runs until you approve it, and the autonomy dial may still refuse. The token stays in this page only.</p>
      <form className="hstack" onSubmit={(e) => { e.preventDefault(); if (token) { setActive(token); setRefresh((n) => n + 1) } }} data-testid="agentapprovals-token-form">
        <label htmlFor={tokenId}>Bearer token</label>
        <input id={tokenId} type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} data-testid="agentapprovals-token" />
        <button type="submit" disabled={!token} data-testid="agentapprovals-load">Load inbox</button>
      </form>
      {!active && <p className="muted" data-testid="agentapprovals-notoken">Paste a bearer token for the project (a role allowed to read or approve agent actions) to load the inbox.</p>}

      {active && stats.s === 'ok' && stats.v.length > 0 && (
        <ul role="list" aria-label="Agent statistics" data-testid="agent-stats" className="hstack" style={{ listStyle: 'none', padding: 0, margin: 0, flexWrap: 'wrap' }}>
          {stats.v.map((a) => (
            <li key={a.agent} data-testid={`agent-stat-${a.agent}`} className="small-text">
              <strong>{a.agent}</strong>: {a.runs} runs, {a.proposals} proposals, {a.executed} executed, {a.rejected} rejected, {a.pending} pending, success rate <span data-testid={`agent-rate-${a.agent}`}>{successRate(a.success_rate_bp)}</span>
            </li>
          ))}
        </ul>
      )}
      {active && stats.s === 'error' && <p role="alert" className="error-text" data-testid="agent-stats-error">Statistics unavailable: {stats.m}</p>}

      {active && (
        <div className="hstack" role="group" aria-label="Inbox controls">
          <label htmlFor={statusId}>Status</label>
          <select id={statusId} value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); setRowFocus(0); setForms(null) }} data-testid="agentapprovals-status">
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
          <button type="button" className="ghost small" onClick={() => setRefresh((n) => n + 1)} data-testid="agentapprovals-refresh">Refresh</button>
        </div>
      )}
      <p role="status" aria-live="polite" className="small-text muted" data-testid="agentapprovals-live">
        {active && list.s === 'ok' ? `${total} ${STATUS_LABEL[status] ?? status} proposal${total === 1 ? '' : 's'}${total > 0 ? `, showing ${pg.from} to ${pg.to}` : ''}.` : ''}
      </p>
      {notice && <p role="status" data-testid="agentapprovals-notice">{notice}</p>}

      {active && list.s === 'loading' && <p className="muted" data-testid="agentapprovals-loading">Loading proposals…</p>}
      {active && list.s === 'error' && <p role="alert" className="error-text" data-testid="agentapprovals-error">{list.m}</p>}
      {active && list.s === 'ok' && items.length === 0 && <p className="muted" data-testid="agentapprovals-empty">No proposals with status {STATUS_LABEL[status] ?? status}.</p>}

      {active && list.s === 'ok' && items.length > 0 && (
        <div className="stack">
          <ul role="list" aria-label="Proposals" data-testid="proposal-list" style={{ listStyle: 'none', padding: 0, margin: 0 }} className="stack">
            {items.map((p, i) => {
              const run = runs[p.run_id]
              const open = forms?.id === p.id ? forms.kind : null
              return (
                <li key={p.id} data-testid={`proposal-${p.id}`}>
                  <article aria-label={`${p.agent}: ${p.action}`} className="stack">
                    <h2 style={{ margin: 0 }}>
                      <button
                        type="button" ref={(el) => { if (el) rowRefs.current.set(i, el); else rowRefs.current.delete(i) }}
                        tabIndex={i === Math.min(rowFocus, items.length - 1) ? 0 : -1}
                        onFocus={() => setRowFocus(i)} onKeyDown={(e) => onRowKey(e, i)} className="ghost" data-testid={`proposal-head-${p.id}`}
                      >{p.agent} proposes {p.action}</button>{' '}
                      <span className="small-text" data-testid={`proposal-risk-${p.id}`} style={{ ...riskColors(p.risk), padding: '0 6px', borderRadius: 4 }}>{riskLabel(p.risk)}</span>{' '}
                      <span className="small-text muted" data-testid={`proposal-status-${p.id}`}>{STATUS_LABEL[p.status] ?? p.status}</span>
                    </h2>
                    <p className="small-text muted" data-testid={`proposal-meta-${p.id}`}>
                      Allowed autonomy: {p.allowed_autonomy}{p.handoff_role ? ` · handed to ${p.handoff_role}` : ''}{p.error_code ? ` · failed: ${p.error_code}` : ''}{p.reason ? ` · ${p.reason}` : ''}
                    </p>
                    <pre tabIndex={0} aria-label={`Arguments of ${p.action}`} data-testid={`proposal-args-${p.id}`} style={{ whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>{argsText(p.args)}</pre>
                    <div className="hstack">
                      <button type="button" className="ghost small" aria-expanded={!!run} disabled={busy} onClick={() => void showRun(p)} data-testid={`run-link-${p.id}`}>Run goal</button>
                      {run && (typeof run === 'string'
                        ? <span role="alert" className="error-text small-text" data-testid={`run-goal-${p.id}`}>{run}</span>
                        : <span className="small-text" data-testid={`run-goal-${p.id}`}>Goal: {run.goal}</span>)}
                    </div>
                    {p.outcome && <p className="small-text" data-testid={`proposal-outcome-${p.id}`}>Outcome: {OUTCOME_LABEL[p.outcome] ?? p.outcome}</p>}
                    <div className="hstack" role="group" aria-label={`Actions for ${p.action}`}>
                      {canDecide(p.status) && <button type="button" disabled={busy} onClick={() => void act(p, 'approve', {}, 'approved.')} data-testid={`approve-${p.id}`}>Approve</button>}
                      {canAcknowledge(p.status) && <button type="button" disabled={busy} onClick={() => void act(p, 'acknowledge', undefined, 'acknowledged.')} data-testid={`acknowledge-${p.id}`}>Acknowledge</button>}
                      {canReject(p.status) && <button type="button" className="outline" disabled={busy} onClick={() => { setForms({ id: p.id, kind: 'reject' }); setText('') }} data-testid={`reject-${p.id}`}>Reject</button>}
                      {canHandOff(p.status) && <button type="button" className="outline" disabled={busy} onClick={() => { setForms({ id: p.id, kind: 'handoff' }); setText('') }} data-testid={`handoff-${p.id}`}>Hand off</button>}
                      {canMarkOutcome(p) && OUTCOMES.map((o) => (
                        <button key={o} type="button" className="outline small" disabled={busy} onClick={() => void act(p, 'outcome', { outcome: o }, `outcome recorded as ${OUTCOME_LABEL[o].toLowerCase()}.`)} data-testid={`outcome-${o}-${p.id}`}>{OUTCOME_LABEL[o]}</button>
                      ))}
                    </div>
                    {open && (
                      <div className="hstack" data-testid={`form-${open}-${p.id}`}>
                        <label htmlFor={textId}>{open === 'reject' ? 'Reason (optional)' : 'Hand off to role'}</label>
                        <input id={textId} value={text} maxLength={open === 'reject' ? 500 : 100} onChange={(e) => setText(e.target.value)} data-testid="agentapprovals-text" autoFocus />
                        {open === 'reject'
                          ? <button type="button" className="danger" disabled={busy} onClick={() => void act(p, 'reject', text.trim() ? { reason: text.trim() } : {}, 'rejected.')} data-testid="confirm-reject">Confirm reject</button>
                          : <button type="button" disabled={busy || !text.trim()} onClick={() => void act(p, 'handoff', { to_role: text.trim() }, `handed off to ${text.trim()}.`)} data-testid="confirm-handoff">Confirm hand off</button>}
                        <button type="button" className="ghost" onClick={() => setForms(null)} data-testid="cancel-form">Cancel</button>
                      </div>
                    )}
                    {errors[p.id] && <p role="alert" className="error-text" data-testid={`proposal-error-${p.id}`}>{errors[p.id]}</p>}
                  </article>
                </li>
              )
            })}
          </ul>
          <div className="hstack" role="group" aria-label="Inbox pages">
            <button type="button" className="outline small" disabled={!pg.hasPrev} onClick={() => { setOffset(Math.max(0, offset - LIMIT)); setRowFocus(0) }} data-testid="agentapprovals-prev">Previous</button>
            <span className="small-text muted" data-testid="agentapprovals-range">{pg.from} to {pg.to} of {total}</span>
            <button type="button" className="outline small" disabled={!pg.hasNext} onClick={() => { setOffset(offset + LIMIT); setRowFocus(0) }} data-testid="agentapprovals-next">Next</button>
          </div>
        </div>
      )}
    </section>
  )
}
