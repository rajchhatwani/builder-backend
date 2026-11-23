import { useId, useRef, useState } from 'react'
import type { PreviewSession } from '../preview/previewSession'
import { State, errText, ok2xx, useCall, type Load, type Page } from '../money/moneyShared'
import { newIdempotencyKey } from '../money/moneyLogic'
import { AiPageFrame, Pager, hasArray, isObj, useGet } from './aiShared'
import { AUTONOMY_LABEL, aiErrorMessage, bpText, clip, effectiveStartMode, isDryMode, jsonText, pageInfo, shortId } from './aiLogic'

interface Agent { name: string; stage: string; autonomy: string; actions: string[]; max_actions_per_run: number; require_eval: string | null; eval_ready: boolean | null }
interface Action { name: string; kind: string; description: string; risk: string; max_autonomy: string; entity: string | null; fields: string[] }
interface Registry { agents: Agent[]; actions: Action[] }
interface Stat { agent: string; runs: number; proposals: number; executed: number; rejected: number; pending: number; outcome_success: number; outcome_failure: number; outcome_neutral: number; success_rate_bp: number | null }
interface Proposal { id: string; action: string; kind: string; risk: string; args: Record<string, unknown>; allowed_autonomy: string; status: string; reason: string | null; result: Record<string, unknown> | null; error_code: string | null }
interface Run { id: string; agent: string; goal: string; mode: string; effective_autonomy: string; status: string; error_code: string | null; started_by: string | null; created_at: string; proposals: Proposal[] }
const LIMIT = 20
const WHAT = 'agents API'
const STATUSES = ['', 'completed', 'failed', 'refused']
const MODES = ['', 'suggest', 'draft', 'auto']
const RANK: Record<string, number> = { suggest: 0, draft: 1, auto: 2 }
const isRun = (j: unknown) => isObj(j) && typeof j.id === 'string' && Array.isArray(j.proposals)

function RunDetail({ run, projectId }: { run: Run; projectId: string }) {
  return (
    <div className="stack" data-testid="agent-run-detail">
      <p>Agent {run.agent}, mode {run.mode}, effective autonomy <strong data-testid="run-effective">{run.effective_autonomy}</strong>, outcome <strong data-testid="run-status">{run.status}</strong>{run.error_code ? ` (${run.error_code})` : ''}.</p>
      <p style={{ whiteSpace: 'pre-wrap' }} data-testid="run-goal">Goal: {clip(run.goal, 4000)}</p>
      {run.proposals.length === 0 ? <p className="muted" data-testid="run-no-proposals">This run proposed nothing.</p> : (
        <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Proposals of this run">
          <table className="stage-table" data-testid="run-proposals">
            <caption className="sr-only">Steps the agent proposed in this run. The model wrote the arguments; they are untrusted text.</caption>
            <thead><tr><th scope="col">Action</th><th scope="col">Risk</th><th scope="col">Status</th><th scope="col">Allowed autonomy</th><th scope="col">Arguments (untrusted)</th><th scope="col">Result / reason</th></tr></thead>
            <tbody>{run.proposals.map((p) => (
              <tr key={p.id} data-testid="run-proposal">
                <th scope="row">{p.action} <span className="muted">({p.kind})</span></th><td>{p.risk}</td><td>{p.status}</td><td>{p.allowed_autonomy}</td>
                <td><pre>{clip(jsonText(p.args), 2000)}</pre></td>
                <td>{p.error_code ? `Error: ${p.error_code}. ` : ''}{p.reason ? `${clip(p.reason, 300)} ` : ''}{p.result ? <pre>{clip(jsonText(p.result), 2000)}</pre> : null}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      <p><a href={`#/p/${projectId}/agentactions`} data-testid="run-approvals-link">Review and decide this run's proposals on the Agent approvals page</a></p>
    </div>
  )
}

function Body({ projectId, session }: { projectId: string; session: PreviewSession }) {
  const call = useCall(session)
  const [refresh, setRefresh] = useState(0)
  const registry = useGet<Registry>(call, '/ai/agents', (j) => isObj(j) && Array.isArray(j.agents), WHAT, refresh)
  const stats = useGet<{ agents: Stat[] }>(call, '/ai/agents/stats', hasArray('agents'), WHAT, refresh)

  const [agentFilter, setAgentFilter] = useState(''), [statusFilter, setStatusFilter] = useState(''), [offset, setOffset] = useState(0)
  const qs = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) })
  if (agentFilter) qs.set('agent', agentFilter)
  if (statusFilter) qs.set('status', statusFilter)
  const runs = useGet<Page<Run>>(call, `/ai/agents/runs?${qs}`, hasArray('items'), WHAT, refresh)
  const [selected, setSelected] = useState<string | null>(null)
  const detail: Load<Run> = useGet<Run>(call, selected ? `/ai/agents/runs/${encodeURIComponent(selected)}` : null, isRun, WHAT)

  const ids = { agent: useId(), goal: useId(), mode: useId(), fa: useId(), fs: useId() }
  const [agent, setAgent] = useState(''), [goal, setGoal] = useState(''), [mode, setMode] = useState('')
  const [key, setKey] = useState(newIdempotencyKey)
  const [confirm, setConfirm] = useState(false)
  const [starting, setStarting] = useState(false)
  const busy = useRef(false)
  const [error, setError] = useState<string | null>(null)
  const [started, setStarted] = useState<Run | null>(null)

  const agents = registry.s === 'ok' ? registry.v.agents : []
  const chosen = agents.find((a) => a.name === agent)
  const startMode = chosen ? effectiveStartMode(mode, chosen.autonomy) : ''
  const dry = isDryMode(startMode)
  const edit = (f: () => void) => { f(); setConfirm(false); setKey(newIdempotencyKey()) }

  async function start() {
    if (busy.current) return
    setError(null); setStarted(null)
    if (!chosen) { setError('Choose an agent.'); setConfirm(false); return }
    if (!goal.trim()) { setError('Describe the goal.'); setConfirm(false); return }
    busy.current = true; setStarting(true)
    try {
      const body: Record<string, unknown> = { goal: goal.trim(), idempotency_key: key }
      if (startMode) body.mode = startMode
      const r = await call('POST', `/ai/agents/${encodeURIComponent(chosen.name)}/runs`, body)
      if (ok2xx(r.status) && isRun(r.json)) {
        setStarted(r.json as unknown as Run); setConfirm(false); setGoal(''); setKey(newIdempotencyKey()); setOffset(0); setRefresh((n) => n + 1)
      } else { setError(ok2xx(r.status) ? 'The API answered with something unexpected.' : aiErrorMessage(r.status, r.json, WHAT)); setConfirm(false) }
    } catch (e) { setError(errText(e, `Could not reach the ${WHAT}`)); setConfirm(false) } finally { busy.current = false; setStarting(false) }
  }

  return (
    <>
      <div className="hstack">
        <button type="button" className="outline" onClick={() => setRefresh((n) => n + 1)} data-testid="agents-refresh">Refresh</button>
        <a href={`#/p/${projectId}/agentactions`} data-testid="agents-approvals-link">Agent approvals (proposals waiting for a human)</a>
      </div>
      <p className="muted" data-testid="agents-note">Agents can only do what the action registry allows. Suggest mode is dry: it proposes and nothing runs. Anything above suggest asks for confirmation here, and high-risk actions always wait for a human.</p>

      <div className="stack">
        <h2>Agent registry</h2>
        <State l={registry} id="registry" empty={(v) => v.agents.length === 0} emptyText="This project defines no agents.">
          {(v) => (
            <>
              <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Agents">
                <table className="stage-table" data-testid="registry-table">
                  <caption className="sr-only">Agents and their autonomy ceiling</caption>
                  <thead><tr><th scope="col">Agent</th><th scope="col">Autonomy ceiling</th><th scope="col">Actions</th><th scope="col">Max actions per run</th><th scope="col">Required eval</th></tr></thead>
                  <tbody>{v.agents.map((a) => (
                    <tr key={a.name} data-testid="registry-agent">
                      <th scope="row">{a.name}</th><td>{a.autonomy}</td><td>{a.actions.join(', ') || 'none'}</td><td className="num">{a.max_actions_per_run}</td>
                      <td>{a.require_eval ? `${a.require_eval}: ${a.eval_ready ? 'passed' : 'not passed yet'}` : 'none'}</td>
                    </tr>))}</tbody>
                </table>
              </div>
              {v.actions.length > 0 && (
                <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Actions">
                  <table className="stage-table" data-testid="registry-actions">
                    <caption className="sr-only">The action registry: the only things an agent can ever do</caption>
                    <thead><tr><th scope="col">Action</th><th scope="col">Kind</th><th scope="col">Risk</th><th scope="col">Max autonomy</th><th scope="col">Description</th></tr></thead>
                    <tbody>{v.actions.map((a) => (
                      <tr key={a.name}><th scope="row">{a.name}</th><td>{a.kind}{a.entity ? ` (${a.entity})` : ''}</td><td>{a.risk}</td><td>{a.max_autonomy}</td><td>{a.description}</td></tr>))}</tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </State>
      </div>

      <div className="stack">
        <h2>Stats</h2>
        <State l={stats} id="stats" empty={(v) => v.agents.length === 0} emptyText="No agent activity yet.">
          {(v) => (
            <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Agent stats">
              <table className="stage-table" data-testid="stats-table">
                <caption className="sr-only">Runs and proposal outcomes per agent</caption>
                <thead><tr><th scope="col">Agent</th><th scope="col">Runs</th><th scope="col">Proposals</th><th scope="col">Executed</th><th scope="col">Rejected</th><th scope="col">Pending</th><th scope="col">Worked / failed / neutral</th><th scope="col">Success rate</th></tr></thead>
                <tbody>{v.agents.map((s) => (
                  <tr key={s.agent} data-testid="stats-row"><th scope="row">{s.agent}</th><td className="num">{s.runs}</td><td className="num">{s.proposals}</td><td className="num">{s.executed}</td><td className="num">{s.rejected}</td><td className="num">{s.pending}</td>
                    <td>{s.outcome_success} / {s.outcome_failure} / {s.outcome_neutral}</td><td>{s.success_rate_bp === null ? 'no outcomes yet' : bpText(s.success_rate_bp)}</td></tr>))}</tbody>
              </table>
            </div>
          )}
        </State>
      </div>

      <form className="stack" data-testid="start-form" onSubmit={(e) => { e.preventDefault(); setError(null); setStarted(null); if (!chosen) { setError('Choose an agent.'); return } if (!goal.trim()) { setError('Describe the goal.'); return } if (dry) void start(); else setConfirm(true) }}>
        <h2>Start a run</h2>
        {registry.s !== 'ok' || agents.length === 0 ? <p className="muted" data-testid="start-unavailable">No agent is available to run.</p> : (
          <>
            <label htmlFor={ids.agent}>Agent</label>
            <select id={ids.agent} value={agent} onChange={(e) => edit(() => { setAgent(e.target.value); setMode('') })} data-testid="start-agent">
              <option value="">Choose…</option>
              {agents.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
            </select>
            <label htmlFor={ids.goal}>Goal</label>
            <textarea id={ids.goal} rows={3} maxLength={4000} value={goal} onChange={(e) => edit(() => setGoal(e.target.value))} data-testid="start-goal" />
            <label htmlFor={ids.mode}>Mode</label>
            <select id={ids.mode} value={mode} onChange={(e) => edit(() => setMode(e.target.value))} data-testid="start-mode">
              {MODES.filter((m) => !m || !chosen || (RANK[m] ?? 99) <= (RANK[chosen.autonomy] ?? 0)).map((m) => <option key={m} value={m}>{m || 'Agent default'}</option>)}
            </select>
            {chosen && (
              <p data-testid="start-mode-note" role="status">
                This run will start in {startMode} mode. {AUTONOMY_LABEL[startMode] ?? ''} {dry ? '' : 'It is not a dry run.'}
                {chosen.require_eval && startMode === 'auto' && !chosen.eval_ready ? ` The eval suite ${chosen.require_eval} has not passed, so the server will refuse auto mode.` : ''}
              </p>
            )}
            <div><button type="submit" disabled={starting} data-testid="start-run">{starting ? 'Starting…' : dry ? 'Start dry run' : 'Start run'}</button></div>
            {confirm && chosen && (
              <div role="alertdialog" aria-label="Confirm run" className="hstack" data-testid="start-confirm">
                <span>Start {chosen.name} in {startMode} mode? This is not a dry run: its proposals {startMode === 'auto' ? 'may execute without a human (low-risk actions)' : 'will wait for a human to approve'}. High-risk actions always wait for a human.</span>
                <button type="button" disabled={starting} onClick={() => void start()} data-testid="start-yes">{starting ? 'Starting…' : `Yes, start in ${startMode} mode`}</button>
                <button type="button" className="outline" disabled={starting} onClick={() => setConfirm(false)}>Cancel</button>
              </div>
            )}
          </>
        )}
        {error && <p role="alert" className="error-text" data-testid="start-error">{error}</p>}
        {started && <div data-testid="start-ok"><h3>Run started</h3><RunDetail run={started} projectId={projectId} /></div>}
      </form>

      <div className="stack">
        <h2>Runs</h2>
        <div className="hstack">
          <label htmlFor={ids.fa}>Agent</label>
          <select id={ids.fa} value={agentFilter} onChange={(e) => { setAgentFilter(e.target.value); setOffset(0) }} data-testid="runs-agent">
            <option value="">Any</option>
            {agents.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
          </select>
          <label htmlFor={ids.fs}>Status</label>
          <select id={ids.fs} value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setOffset(0) }} data-testid="runs-status">
            {STATUSES.map((s) => <option key={s} value={s}>{s || 'Any'}</option>)}
          </select>
        </div>
        <State l={runs} id="runs" empty={(v) => v.items.length === 0} emptyText="No runs yet.">
          {(v) => (
            <>
              <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Agent runs">
                <table className="stage-table" data-testid="runs-table">
                  <caption className="sr-only">Agent runs, newest first</caption>
                  <thead><tr><th scope="col">When</th><th scope="col">Agent</th><th scope="col">Mode</th><th scope="col">Effective</th><th scope="col">Status</th><th scope="col">Proposals</th><th scope="col">By</th><th scope="col">Detail</th></tr></thead>
                  <tbody>{v.items.map((r) => (
                    <tr key={r.id} data-testid="run-row">
                      <td>{r.created_at}</td><th scope="row">{r.agent}</th><td>{r.mode}</td><td>{r.effective_autonomy}</td><td>{r.status}{r.error_code ? ` (${r.error_code})` : ''}</td><td className="num">{r.proposals.length}</td><td>{shortId(r.started_by)}</td>
                      <td><button type="button" className="outline small" aria-label={`Show run of ${r.agent} from ${r.created_at}`} onClick={() => { setSelected(r.id); setStarted(null) }} data-testid="run-open">Show</button></td>
                    </tr>))}</tbody>
                </table>
              </div>
              <Pager id="runs" info={pageInfo(Number(v.total), LIMIT, offset)} onPrev={() => setOffset(Math.max(0, offset - LIMIT))} onNext={() => setOffset(offset + LIMIT)} />
            </>
          )}
        </State>
        {selected && (
          <div className="stack">
            <h3>Run detail</h3>
            <State l={detail} id="run-detail" empty={() => false} emptyText="">{(r) => <RunDetail run={r} projectId={projectId} />}</State>
          </div>
        )}
      </div>
    </>
  )
}

export function AgentRunsPage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  return (
    <AiPageFrame projectId={projectId} session={session} testid="agent-runs-page" title="Agent runs"
      intro="The agents this project defines, what they have done and how well it worked. Proposals that need a person are decided on the Agent approvals page.">
      {(s) => <Body projectId={projectId} session={s} />}
    </AiPageFrame>
  )
}
