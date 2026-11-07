import { useCallback, useEffect, useState } from 'react'
import { aiApi } from './aiApi'
import { approvalIdFromHash, approvalsLink, decisionGate, describePayload, effectiveState, expiryText, kindLabel, noteValid, reviewHref, riskLabel, stateLabel, type Tab } from './approvalLogic'
import { Proposed, ProvenanceBadge } from './Provenance'
import type { Approval } from './types'
import { errMsg } from './useRunParam'
import { useMyRole } from './useMyRole'

function useApprovalParam(): string | null {
  const [id, setId] = useState(() => approvalIdFromHash(window.location.hash))
  useEffect(() => {
    const on = () => setId(approvalIdFromHash(window.location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return id
}

function Risks({ flags }: { flags: string[] }) {
  if (flags.length === 0) return null
  return <span data-testid="risk-flags">{flags.map((f) => <span key={f} className="badge badge-muted" data-flag={f}>{riskLabel(f)}</span>)} </span>
}

/** F3-4: inbox of approvals. The review screen opens in place when `?approval=<id>` is set. */
export function ApprovalsPage({ projectId }: { projectId: string }) {
  const approvalId = useApprovalParam()
  return approvalId ? <ReviewScreen projectId={projectId} approvalId={approvalId} /> : <Inbox projectId={projectId} />
}

function Inbox({ projectId }: { projectId: string }) {
  const [tab, setTab] = useState<Tab>('pending')
  const [items, setItems] = useState<Approval[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const myRole = useMyRole(projectId)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      // the server's "decided" is every closed state; list all and split here so expired ones land in the right tab
      const all = await aiApi.listApprovals(projectId, tab === 'pending' ? { state: 'pending' } : {})
      setItems(all.filter((a) => (tab === 'pending' ? effectiveState(a) === 'pending' : effectiveState(a) !== 'pending')))
      setError('')
    } catch (e) { setError(errMsg(e)) } finally { setLoading(false) }
  }, [projectId, tab])
  useEffect(() => { void load() }, [load])

  return (
    <section data-testid="approvals-page">
      <h1>Approvals</h1>
      <p className="muted">Things the agent asked a person to decide. Nothing here changes until someone approves it.</p>
      {error && <p className="bh-error" role="alert">{error}</p>}
      <div role="tablist" aria-label="Approvals" className="bh-tabs">
        {(['pending', 'decided'] as Tab[]).map((t) => (
          <button key={t} role="tab" id={`apptab-${t}`} aria-selected={tab === t} aria-controls="approvals-panel" className={tab === t ? '' : 'outline'} data-testid={`tab-${t}`} onClick={() => setTab(t)}>
            {t === 'pending' ? 'Waiting for you' : 'Decided'}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="approvals-panel" aria-labelledby={`apptab-${tab}`}>
        {loading && <p className="empty-state">Loading…</p>}
        {!loading && items.length === 0 && <p className="empty-state" data-testid="approvals-empty">{tab === 'pending' ? 'Nothing is waiting for you.' : 'No decisions yet.'}</p>}
        {!loading && items.length > 0 && (
          <ul className="ai-list" data-testid="approvals-list">
            {items.map((a) => {
              const st = effectiveState(a)
              const gate = decisionGate(a, myRole)
              return (
                <li key={a.id} className="ai-item" data-testid="approval-row" data-kind={a.kind} data-state={st}>
                  <div className="hstack">
                    <span className="badge" data-testid="row-kind">{a.kind} · {kindLabel(a.kind)}</span>
                    {a.requires_owner && <span className="badge badge-outline" data-testid="owner-badge">Owner only</span>}
                    <span className="badge badge-muted">{stateLabel(st)}</span>
                    <span className="grow" />
                    <small className="muted" data-testid="row-expiry">{expiryText({ ...a, state: st })}</small>
                  </div>
                  <p><a href={reviewHref(projectId, a)} data-testid="row-open">{a.subject}</a></p>
                  <div className="hstack">
                    <Risks flags={a.risk_flags} />
                    <a className="small-text" href={`#/p/${projectId}/build?run=${a.run_id}`}>run {a.run_id.slice(0, 8)}</a>
                  </div>
                  {st === 'pending' && a.requires_owner && !gate.canDecide && <small className="muted" data-testid="row-owner-note">{gate.reason}</small>}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}

const INTRO: Record<string, string> = {
  B: 'The agent changed the app spec. This is what it wants to keep.',
  C: 'The agent finished and wants its change reviewed, including any code it wrote.',
  D: 'This change could remove data or weaken security. It does nothing until you approve it.',
  E: 'The agent wants to do something outside the project. It does nothing until you approve it.',
}

export function ReviewScreen({ projectId, approvalId }: { projectId: string; approvalId: string }) {
  const [a, setA] = useState<Approval | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [denyTried, setDenyTried] = useState(false)
  const [done, setDone] = useState('')
  const myRole = useMyRole(projectId)

  useEffect(() => {
    let off = false
    aiApi.getApproval(projectId, approvalId).then((x) => {
      if (!off) setA(x)
    }, (e) => { if (!off) setError(errMsg(e)) }).finally(() => { if (!off) setLoading(false) })
    return () => { off = true }
  }, [projectId, approvalId])

  const decide = async (approve: boolean) => {
    if (!a) return
    if (!noteValid(approve, note)) { setDenyTried(true); return }
    setBusy(true); setError('')
    try {
      setA(await aiApi.decide(projectId, a.id, approve, note.trim()))
      setDone(approve ? 'Approved. Resume the run from the build view to continue.' : 'Denied.')
    } catch (e) { setError(errMsg(e)) } finally { setBusy(false) }
  }

  const back = <a href={approvalsLink(projectId)} data-testid="back-to-inbox">Back to approvals</a>
  if (loading) return <section data-testid="review-page"><h1>Review</h1><p className="empty-state">Loading…</p></section>
  if (!a) return <section data-testid="review-page"><h1>Review</h1>{error && <p className="bh-error" role="alert">{error}</p>}<p className="empty-state" data-testid="review-missing">This approval was not found.</p>{back}</section>
  if (a.kind === 'A') return <section data-testid="review-page"><h1>Review</h1><p>The plan is reviewed on its own page. <a href={reviewHref(projectId, a)}>Open the plan</a></p>{back}</section>

  const st = effectiveState(a)
  const gate = decisionGate(a, myRole)
  const d = describePayload(a.payload)
  const open = st === 'pending'
  const Wrap = open ? Proposed : 'div'
  const noteId = 'review-note'

  return (
    <section data-testid="review-page" data-kind={a.kind} data-state={st}>
      <p>{back}</p>
      <h1>{kindLabel(a.kind)} review</h1>
      <p className="muted">{INTRO[a.kind] ?? ''}</p>
      {error && <p className="bh-error" role="alert" data-testid="review-error">{error}</p>}
      {st !== 'pending' && (
        <p className="card" role="status" data-testid="review-state" data-state={st}>
          <strong>{stateLabel(st)}.</strong>{' '}
          {st === 'expired' && 'It was not decided in time, so it can no longer be approved. The agent has to ask again.'}
          {st === 'superseded' && 'The spec or the agent moved on. Look for the newer request in the inbox.'}
          {(st === 'approved' || st === 'denied') && a.decision_note && <>Note: {a.decision_note}</>}
        </p>
      )}
      <div className="card" data-testid="review-card">
        <div className="hstack">
          <h2 className="grow">{a.subject}</h2>
          <ProvenanceBadge author="ai" projectId={projectId} runId={a.run_id} />
        </div>
        <div className="hstack">
          {a.requires_owner && <span className="badge badge-outline" data-testid="owner-badge">Owner only</span>}
          <Risks flags={a.risk_flags} />
          <small className="muted" data-testid="review-expiry">{expiryText({ ...a, state: st })}</small>
        </div>
        {a.risk_flags.length === 0 && <p className="muted small-text" data-testid="no-risks">No risk flags were raised.</p>}

        <Wrap>
          {d.summary && <p data-testid="review-summary">{d.summary}</p>}
          {d.diffRows.length > 0 && (
            <div data-testid="review-diff"><h3>Spec changes</h3>
              <ul className="ai-files">
                {d.diffRows.map((r) => (
                  <li key={r.section} data-testid="diff-row" data-section={r.section}>
                    <strong>{r.section}</strong>
                    {r.changedOnly && <span> changed</span>}
                    {r.added.length > 0 && <div data-testid="diff-added">Added: {r.added.map((n) => <code key={n}>{n} </code>)}</div>}
                    {r.removed.length > 0 && <div data-testid="diff-removed">Removed: {r.removed.map((n) => <code key={n}>{n} </code>)}</div>}
                    {r.changed.length > 0 && <div data-testid="diff-changed">Changed: {r.changed.map((n) => <code key={n}>{n} </code>)}</div>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {d.specDiff.length > 0 && (
            <div data-testid="review-diff-text">{d.diffRows.length === 0 && <h3>Spec changes</h3>}<pre className="ai-diff">{d.specDiff.join('\n')}</pre></div>
          )}
          {d.hooks.length > 0 && (
            <div data-testid="review-hooks">
              <h3>Custom logic (hooks)</h3>
              <ul className="ai-files">
                {d.hooks.map((h) => (
                  <li key={h.name} data-testid="hook-row" data-ai={h.ai}>
                    <code>{h.name}</code> <ProvenanceBadge author={h.ai ? 'ai' : h.author} projectId={projectId} runId={a.run_id} />
                    {h.ai && <small className="muted"> AI-written code: read it before you approve.</small>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {d.files.length > 0 && (
            <div data-testid="review-files"><h3>Files ({d.files.length})</h3><ul className="ai-files">{d.files.map((f) => <li key={f}><code>{f}</code></li>)}</ul></div>
          )}
          {d.facts.length > 0 && (
            <dl className="bh-summary" data-testid="review-facts">{d.facts.map((f) => <div key={f.key}><dt>{f.key}</dt><dd>{f.value}</dd></div>)}</dl>
          )}
        </Wrap>
        {a.kind === 'C' && (
          <p data-testid="review-gates">
            Gate results: {d.gatesGreen && <strong data-testid="gates-green">G0-G9 green. </strong>}{d.gateHash ? <>report <code>{d.gateHash.slice(0, 12)}</code>. The checks ran against exactly this change.</> : <span className="muted">not attached to this request.</span>}
          </p>
        )}
        {!d.summary && d.specDiff.length === 0 && d.diffRows.length === 0 && d.hooks.length === 0 && d.files.length === 0 && d.facts.length === 0 && (
          <p className="muted" data-testid="review-nothing">The request carries no further details.</p>
        )}

        {open && (
          <>
            <label htmlFor={noteId}>Note (required to deny)</label>
            <input id={noteId} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} aria-invalid={denyTried && !note.trim()} aria-describedby="note-help" data-testid="review-note" />
            <small id="note-help" className={denyTried && !note.trim() ? 'bh-error' : 'muted'} data-testid="note-help">
              {denyTried && !note.trim() ? 'Say why you are denying so the agent can adjust.' : 'Optional when you approve.'}
            </small>
            {!gate.canDecide && <p className="muted" role="note" id="gate-reason" data-testid="gate-reason">{gate.reason}</p>}
            <div className="hstack">
              <button disabled={busy || !gate.canDecide} aria-describedby={!gate.canDecide ? 'gate-reason' : undefined} onClick={() => void decide(true)} data-testid="review-approve">Approve</button>
              <button className="outline" disabled={busy || !gate.canDecide} onClick={() => void decide(false)} data-testid="review-deny">Deny</button>
            </div>
          </>
        )}
        {done && <p role="status" data-testid="review-done">{done} <a href={`#/p/${projectId}/build?run=${a.run_id}`}>Back to the build</a></p>}
      </div>
    </section>
  )
}
