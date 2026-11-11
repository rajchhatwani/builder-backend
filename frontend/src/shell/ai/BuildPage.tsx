import { Suspense, lazy, useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { aiApi } from './aiApi'
import { approvalList, effectiveState, reviewHref } from './approvalLogic'
import { ProvenanceBadge } from './Provenance'
import { POLL_MS, STAGE_TABS, TAB_READY, budgetRows, canSeeItWork, friendlyStep, gateRows, pendingFor, platformRow, pollInterval, runActions, runStateLabel, stepLine, stopInfo, type StageTab } from './buildLogic'
import { trapTab } from './focusTrap'
import { LEAVE_MESSAGE, useLeaveBuildGuard } from './leaveGuard'
import { PLAN_KEYS, PLAN_LABEL, phasesOf, planRows } from './planLogic'
import { tokenFor } from './seeItLogic'
import type { Approval, GateRunResult, PlatformBudget, Preview, RunDetail } from './types'
import { useNow } from './useNow'
import { errMsg, useRunParam, runLink } from './useRunParam'

const StageTabs = lazy(() => import('./StageTabs').then((m) => ({ default: m.StageTabs })))
function GateReport({ r }: { r: GateRunResult }) {
  const rows = gateRows(r.failures)
  return (
    <div className="card" data-testid="gate-report" data-ok={r.ok} role="status">
      <h2>{r.ok ? 'All checks passed' : `${r.failure_count} ${r.failure_count === 1 ? 'check' : 'checks'} failed`}</h2>
      {r.ok && <p data-testid="gate-pass">Every gate passed on the current draft.</p>}
      {rows.length > 0 && (
        <ul data-testid="gate-list">
          {rows.map((g, i) => (
            <li key={`${g.id}-${i}`} data-testid="gate-row" data-gate={g.id} data-ok="false">
              <span className="badge badge-muted" data-testid="gate-id">{g.id}</span> <span className="ai-bad">fail</span>{' '}
              <span data-testid="gate-message">{g.message}</span>
              {g.detail.length > 0 && <small className="muted"> {g.detail.map(([k, v]) => `${k}: ${v}`).join(' | ')}</small>}
            </li>
          ))}
        </ul>
      )}
      {r.failure_count > rows.length && <p className="muted small-text">Showing the first {rows.length} of {r.failure_count}.</p>}
      <p className="muted small-text">Report <code data-testid="gate-hash">{r.report_hash.slice(0, 12)}</code>. Read-only: nothing was changed.</p>
    </div>
  )
}

const TAB_LABEL: Record<StageTab, string> = { gates: 'Gates', details: 'Details', plan: 'Plan', diagrams: 'Diagrams', api: 'API', stage: 'Code, logs and data' }

function PlatformBar({ b, error }: { b: PlatformBudget | null; error: boolean }) {
  if (error) return <div data-testid="budget-platform" data-level="unknown"><strong>Platform total</strong> <span className="muted small-text">Not available right now.</span></div>
  if (!b) return null
  const r = platformRow(b)
  return (
    <div data-testid="budget-platform" data-level={r.level}>
      <div className="hstack"><strong>Platform total</strong><span className="muted small-text" data-testid="budget-platform-text">{r.text}</span>{r.remaining && <span className={r.limitReached ? 'ai-bad' : 'muted small-text'} data-testid="budget-platform-remaining">{r.remaining}</span>}</div>
      {r.pct !== null && <progress max={100} value={r.pct} aria-label="Platform budget used" />}
      {r.limitReached && <p className="bh-error" role="alert" data-testid="budget-limit">The platform AI budget is used up. Runs that need the model cannot continue until it is raised.</p>}
    </div>
  )
}

function Budgets({ run, platform, platformError }: { run: RunDetail; platform: PlatformBudget | null; platformError: boolean }) {
  return (
    <div className="ai-budgets" data-testid="budgets">
      <PlatformBar b={platform} error={platformError} />
      {budgetRows(run).map((b) => (
        <div key={b.key} data-testid={`budget-${b.key}`} data-level={b.level}>
          <div className="hstack"><strong>{b.label}</strong><span className="muted small-text">{b.text}</span></div>
          {b.pct !== null && <progress max={100} value={b.pct} aria-label={`${b.label} used`} />}
        </div>
      ))}
    </div>
  )
}

/** F3-3: one run, live. Polls every 3 s while it can still change. */
export function BuildPage({ projectId, orgSlug }: { projectId: string; orgSlug?: string | null }) {
  const paramRun = useRunParam()
  const [runId, setRunId] = useState<string | null>(paramRun)
  const [run, setRun] = useState<RunDetail | null>(null)
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [tab, setTab] = useState<StageTab>('gates')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [confirmTake, setConfirmTake] = useState(false)
  const [platform, setPlatform] = useState<PlatformBudget | null>(null)
  const [platformError, setPlatformError] = useState(false)
  const [gateReport, setGateReport] = useState<GateRunResult | null>(null)
  const [stagePreview, setStagePreview] = useState<Preview | null>(null)
  const inflight = useRef<string | null>(null) // S3-002: the run a refresh is in flight for
  const current = useRef<string | null>(runId)

  const codeDirty = useRef(false) // S3-010: the code view reports unsaved edits
  const now = useNow()
  const onDirty = useCallback((d: boolean) => { codeDirty.current = d }, [])
  useLeaveBuildGuard(codeDirty, projectId) // S3-010r: leaving the section
  const wasTaking = useRef(false)
  const takeRef = useRef<HTMLDivElement>(null)
  const takeBtn = useRef<HTMLButtonElement>(null)
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  useEffect(() => {
    if (!paramRun) return
    if (paramRun !== current.current && current.current && codeDirty.current && !window.confirm('Discard your unsaved code changes and open another run?')) {
      window.location.hash = runLink(projectId, 'build', current.current) // stay on the run being edited
      return
    }
    codeDirty.current = false
    setRunId(paramRun)
  }, [paramRun, projectId])
  useEffect(() => {
    if (confirmTake) takeRef.current?.focus()
    else if (wasTaking.current) takeBtn.current?.focus() // restore focus however the dialog closed
    wasTaking.current = confirmTake
  }, [confirmTake])
  const closeTake = () => setConfirmTake(false)
  // S3-010r: leaving the code view (another tab) drops unsaved edits, so ask first
  const selectTab = (t: StageTab) => {
    if (t === tab) return
    if (tab === 'stage' && codeDirty.current) { if (!window.confirm(LEAVE_MESSAGE)) return; codeDirty.current = false }
    setTab(t)
  }
  // switching runs: forget the old run's data so it is never shown under the new id
  useEffect(() => {
    current.current = runId
    if (runId) { setRun(null); setApprovals([]); setError(''); setLoading(true); setGateReport(null) }
  }, [runId])

  // no ?run=: show the latest run
  useEffect(() => {
    if (runId) return
    let off = false
    aiApi.listRuns(projectId, 1).then((p) => { if (off) return; if (p.items[0]) setRunId(p.items[0].id); else setLoading(false) }, (e) => { if (!off) { setError(errMsg(e)); setLoading(false) } })
    return () => { off = true }
  }, [projectId, runId])

  const refresh = useCallback(async () => {
    if (!runId || inflight.current === runId) return
    inflight.current = runId
    try {
      const [r, a] = await Promise.all([aiApi.getRun(projectId, runId), aiApi.listApprovals(projectId, { run_id: runId })])
      if (current.current !== runId) return // a newer run was opened while this was loading
      setRun(r); setApprovals(approvalList(a)); setError('')
    } catch (e) { if (current.current === runId) setError(errMsg(e)) } finally {
      if (inflight.current === runId) inflight.current = null
      if (current.current === runId) setLoading(false)
    }
  }, [projectId, runId])

  useEffect(() => { void refresh() }, [refresh])

  const runState = run?.state
  useEffect(() => {
    if (!orgSlug) return
    let off = false
    aiApi.platformBudget(orgSlug).then((b) => { if (!off) { setPlatform(b); setPlatformError(false) } }, () => { if (!off) setPlatformError(true) })
    return () => { off = true }
  }, [orgSlug, runState])

  const workspaceId = run?.workspace_id ?? null
  useEffect(() => {
    if (tab !== 'stage' || !workspaceId) return
    let off = false
    aiApi.listPreviews(projectId).then((l) => { if (!off) setStagePreview(l.find((p) => p.workspace_id === workspaceId && ['starting', 'running', 'sleeping'].includes(p.state)) ?? null) }, () => undefined)
    return () => { off = true }
  }, [tab, workspaceId, projectId])
  useEffect(() => {
    // S3-001: a resumed `stopped` run is driven inside the resume request; poll while that request is open
    const ms = pollInterval(runState ? { state: runState } : null, false) ?? (busy && runState ? POLL_MS : null)
    if (ms === null) return
    const t = window.setInterval(() => { if (!document.hidden) void refresh() }, ms)
    return () => window.clearInterval(t)
  }, [runState, refresh, busy])

  const act = async (fn: () => Promise<unknown>, background = false): Promise<boolean> => {
    setBusy(true); setError('')
    const p = fn().then(() => { void refresh(); return true }, (e) => { setError(errMsg(e)); return false }).finally(() => setBusy(false))
    // resume drives the run inside the request: keep the page live instead of waiting for it
    return background ? true : p
  }
  const onTabKey = (e: KeyboardEvent) => {
    const i = STAGE_TABS.indexOf(tab)
    const n = e.key === 'ArrowRight' ? (i + 1) % STAGE_TABS.length : e.key === 'ArrowLeft' ? (i + STAGE_TABS.length - 1) % STAGE_TABS.length : e.key === 'Home' ? 0 : e.key === 'End' ? STAGE_TABS.length - 1 : -1
    if (n < 0) return
    e.preventDefault(); selectTab(STAGE_TABS[n]); tabRefs.current[STAGE_TABS[n]]?.focus()
  }

  if (loading) return <section data-testid="build-page"><h1>Build</h1><p className="empty-state">Loading…</p></section>
  if (!runId || !run) {
    return (
      <section data-testid="build-page">
        <h1>Build</h1>
        {error && <p className="bh-error" role="alert">{error}</p>}
        <p className="empty-state" data-testid="build-empty">No build has started yet. <a href={`#/p/${projectId}/intake`}>Describe what you want built</a>.</p>
      </section>
    )
  }

  const stop = stopInfo(run.stop_code, run.stop_detail)
  const pending = pendingFor(approvals, run.id, now)
  const actions = runActions(run, pending.length)
  const gateA = approvals.find((a) => a.kind === 'A')
  const scope = gateA ? planRows(gateA.payload) : []

  return (
    <section data-testid="build-page">
      <h1>Build</h1>
      <p className="ai-goal" data-testid="run-goal">{run.goal}</p>
      <p><ProvenanceBadge author="ai" projectId={projectId} runId={run.id} /> <small className="muted">This build is made by the agent. Nothing it proposes counts until you approve it.</small></p>
      {error && <p className="bh-error" role="alert" data-testid="build-error">{error}</p>}

      <div className="hstack" data-testid="run-chips">
        <span className="badge" data-testid="chip-state">{runStateLabel(run.state)}</span>
        <span className="badge badge-muted" data-testid="chip-phase">Phase: {run.phase}</span>
        {run.stop_code && <span className="badge badge-muted" data-testid="chip-stop">{run.stop_code}</span>}
        <span className="grow" />
        {run.paused_at && actions.paused && <span className="badge badge-muted" data-testid="chip-paused">Paused</span>}
        <button className="outline" disabled={busy || !actions.pause} onClick={() => void act(() => aiApi.pauseRun(projectId, run.id))} data-testid="run-pause" title={actions.pause ? 'Stop at the next step; the draft is kept' : 'Only a running build can be paused'}>Pause</button>
        <button className="outline" disabled={busy || !actions.gates} onClick={() => void act(async () => { setGateReport(await aiApi.runGates(projectId, run.id)) })} data-testid="run-gates">Run gates</button>
        {actions.resume && <button disabled={busy} onClick={() => void act(() => aiApi.resumeRun(projectId, run.id), true)} data-testid="run-resume">{actions.resumeLabel}</button>}
        {actions.cancel && <button className="outline" disabled={busy} onClick={() => void act(() => aiApi.cancelRun(projectId, run.id))} data-testid="run-cancel">Cancel</button>}
        {actions.cancel && <button ref={takeBtn} className="outline" disabled={busy} onClick={() => setConfirmTake(true)} data-testid="run-takeover">Take over</button>}
      </div>
      {confirmTake && (
        <div className="card" role="alertdialog" ref={takeRef} tabIndex={-1} onKeyDown={(e) => { if (e.key === 'Escape') closeTake(); else trapTab(e, takeRef.current) }} aria-labelledby="takeover-title" aria-describedby="takeover-text" data-testid="takeover-confirm">
          <h2 id="takeover-title">Take over from the agent?</h2>
          <p id="takeover-text">This cancels the run. The agent stops and does nothing more; requests it left open can no longer lead to changes. You can then work on the project yourself.</p>
          <div className="hstack">
            <button disabled={busy} onClick={() => void act(() => aiApi.cancelRun(projectId, run.id)).then((ok) => { if (ok) setConfirmTake(false) })} data-testid="takeover-yes">Stop the run and take over</button>
            <button className="outline" disabled={busy} onClick={closeTake} data-testid="takeover-no">Keep the agent running</button>
          </div>
        </div>
      )}
      {gateReport && <GateReport r={gateReport} />}
      {stop && (
        <div className="card" role="status" data-testid="stop-info" data-code={run.stop_code}>
          <h2>{stop.title}</h2>
          {stop.text && <p data-testid="stop-text">{stop.text}</p>}
          {stop.next && <p data-testid="stop-next"><strong>What now:</strong> {stop.next}</p>}
        </div>
      )}
      {!stop && run.stop_detail && <p className="muted" data-testid="stop-detail">{run.stop_detail}</p>}
      {canSeeItWork(run) && (
        <p className="card" data-testid="seeit-cta">The change is in your project. <a href={`#/p/${projectId}/see`} data-testid="seeit-link">See it work</a>: a short guided check that the backend answers.</p>
      )}

      {pending.length > 0 && (
        <div className="card" data-testid="pending-approvals">
          <h2>Waiting for you</h2>
          <ul>
            {pending.map((a) => (
              <li key={a.id}>
                <a href={reviewHref(projectId, a)} data-testid="pending-link">{a.subject}</a>
                {' '}<span className="badge badge-muted">Gate {a.kind}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Budgets run={run} platform={platform} platformError={platformError} />

      <h2>Timeline</h2>
      <ol className="ai-timeline" data-testid="timeline">
        {run.steps.length === 0 && <li className="muted">No steps yet.</li>}
        {run.steps.map((s) => {
          const l = stepLine(s)
          const f = friendlyStep(s)
          if (f) {
            return (
              <li key={s.id} data-testid="step" data-ok={f.tone !== 'bad'} data-friendly={f.tone}>
                <span className="muted">#{s.seq}</span> <span className="badge badge-muted">system</span> {f.text}{' '}
                <span className={f.tone === 'bad' ? 'ai-bad' : f.tone === 'ok' ? 'ai-ok' : 'muted'}>{f.tone === 'bad' ? 'not applied' : f.tone === 'ok' ? 'applied' : 'discarded'}</span>
                {f.next && <small className="muted" data-testid="step-next"> {f.next}</small>}
              </li>
            )
          }
          return (
            <li key={s.id} data-testid="step" data-ok={l.ok}>
              <span className="muted">#{s.seq}</span> <span className="badge badge-muted">{s.kind}</span> {l.what}{' '}
              <span className={l.ok ? 'ai-ok' : 'ai-bad'}>{l.ok ? 'ok' : 'failed'}</span>{' '}
              <span className="muted small-text">{l.cost}</span>
            </li>
          )
        })}
      </ol>
      {run.steps_total > run.steps.length && <p className="muted small-text">Showing the first {run.steps.length} of {run.steps_total} steps.</p>}

      <div role="tablist" aria-label="Stage" className="bh-tabs" onKeyDown={onTabKey}>
        {STAGE_TABS.map((t) => (
          <button key={t} ref={(el) => { tabRefs.current[t] = el }} tabIndex={tab === t ? 0 : -1} role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls="stage-panel" className={tab === t ? '' : 'outline'} onClick={() => selectTab(t)}>{TAB_LABEL[t]}</button>
        ))}
      </div>
      <div role="tabpanel" id="stage-panel" aria-labelledby={`tab-${tab}`} data-testid="stage-panel">
        {!TAB_READY.includes(tab) && <p className="empty-state" data-testid="tab-soon">{TAB_LABEL[tab]}: Coming in a later cycle.</p>}
        {tab === 'stage' && (
          !workspaceId ? <p className="empty-state" data-testid="stage-none">This run has no draft workspace to show.</p> : (
            <Suspense fallback={<p className="empty-state">Loading…</p>}>
              <StageTabs projectId={projectId} workspaceId={workspaceId} previewId={stagePreview?.id} token={stagePreview ? (tokenFor(stagePreview.id) ?? '') : ''} onDirtyChange={onDirty} />
            </Suspense>
          )
        )}
        {tab === 'gates' && (
          approvals.length === 0 ? <p className="empty-state">No approvals asked for yet.</p> : (
            <table data-testid="gates-table">
              <thead><tr><th>Gate</th><th>What</th><th>State</th></tr></thead>
              <tbody>{approvals.map((a) => <tr key={a.id}><td>{a.kind}</td><td>{a.subject}</td><td>{effectiveState(a, now)}</td></tr>)}</tbody>
            </table>
          )
        )}
        {tab === 'details' && (
          <dl className="bh-summary" data-testid="details">
            <dt>Run</dt><dd><code>{run.id}</code></dd>
            <dt>Started</dt><dd>{run.started_at ?? 'not yet'}</dd>
            <dt>Finished</dt><dd>{run.finished_at ?? 'not yet'}</dd>
            <dt>Last change</dt><dd>{run.updated_at}</dd>
          </dl>
        )}
        {tab === 'plan' && (
          !gateA ? <p className="empty-state">No plan has been proposed yet.</p> : (
            <div data-testid="plan-readonly">
              {phasesOf(gateA.payload).length > 0 && <ol>{phasesOf(gateA.payload).map((p, i) => <li key={`${i}-${p}`}>{p}</li>)}</ol>}
              {PLAN_KEYS.map((k) => { const v = scope.filter((r) => r.key === k); return v.length ? <p key={k}><strong>{PLAN_LABEL[k]}:</strong> {v.map((r) => r.value).join(', ')}</p> : null })}
              <p className="muted small-text">Plan {gateA.state}.</p>
            </div>
          )
        )}
      </div>
    </section>
  )
}
