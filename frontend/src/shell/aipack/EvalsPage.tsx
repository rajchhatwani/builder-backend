import { useId, useRef, useState } from 'react'
import type { PreviewSession } from '../preview/previewSession'
import { State, errText, ok2xx, useCall, type Load, type Page } from '../money/moneyShared'
import { AiPageFrame, Pager, hasArray, isArr, isObj, useGet } from './aiShared'
import { aiErrorMessage, bpText, pageInfo, shortId } from './aiLogic'

interface Latest { id: string; passed: boolean; score_bp: number; created_at: string }
interface Suite { name: string; agent: string; pass_bp: number; case_count: number; latest: Latest | null }
interface CaseResult { case: string; passed: boolean; proposed: string[]; error_code: string | null }
interface EvalRun { id: string; suite: string; agent: string; score_bp: number; passed: boolean; total: number; passed_count: number; results: CaseResult[]; created_by: string | null; created_at: string }
const LIMIT = 20
const WHAT = 'eval harness'
const isRun = (j: unknown) => isObj(j) && typeof j.id === 'string' && Array.isArray(j.results)

function reason(r: CaseResult): string {
  if (r.error_code) return `Error: ${r.error_code}`
  return r.passed ? 'Expected actions proposed, none forbidden.' : 'Proposed actions did not match the case (a missing expected action or a forbidden one).'
}

function RunDetail({ run }: { run: EvalRun }) {
  return (
    <div className="stack" data-testid="eval-detail">
      <p>Suite {run.suite} (agent {run.agent}) scored {bpText(run.score_bp)}: {run.passed_count} of {run.total} cases passed. <strong data-testid="eval-verdict">{run.passed ? 'Suite passed' : 'Suite failed'}</strong>. Dry mode: no proposal was executed.</p>
      <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Case results">
        <table className="stage-table" data-testid="eval-cases">
          <caption className="sr-only">Case results of this eval run</caption>
          <thead><tr><th scope="col">Case</th><th scope="col">Result</th><th scope="col">Proposed actions</th><th scope="col">Reason</th></tr></thead>
          <tbody>{run.results.map((r, i) => (
            <tr key={`${r.case}-${i}`} data-testid="eval-case">
              <th scope="row">{r.case}</th><td>{r.passed ? 'Pass' : 'Fail'}</td><td>{r.proposed.length ? r.proposed.join(', ') : 'none'}</td><td>{reason(r)}</td>
            </tr>))}</tbody>
        </table>
      </div>
    </div>
  )
}

function Body({ session }: { session: PreviewSession }) {
  const call = useCall(session)
  const [refresh, setRefresh] = useState(0)
  const [suiteFilter, setSuiteFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [fresh, setFresh] = useState<EvalRun | null>(null)
  const [running, setRunning] = useState<string | null>(null)
  const busy = useRef(false)
  const [runErr, setRunErr] = useState<string | null>(null)
  const filterId = useId()

  const suites = useGet<Suite[]>(call, '/ai/evals/suites', isArr, WHAT, refresh)
  const qs = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) })
  if (suiteFilter.trim()) qs.set('suite', suiteFilter.trim().slice(0, 40))
  const runs = useGet<Page<EvalRun>>(call, `/ai/evals/runs?${qs}`, hasArray('items'), WHAT, refresh)
  const detail: Load<EvalRun> = useGet<EvalRun>(call, selected ? `/ai/evals/runs/${encodeURIComponent(selected)}` : null, isRun, WHAT)

  async function run(name: string) {
    if (busy.current) return
    busy.current = true; setRunning(name); setRunErr(null); setFresh(null)
    try {
      const r = await call('POST', `/ai/evals/suites/${encodeURIComponent(name)}/run`)
      if (ok2xx(r.status) && isRun(r.json)) { setFresh(r.json as unknown as EvalRun); setSelected(null); setOffset(0); setRefresh((n) => n + 1) }
      else setRunErr(ok2xx(r.status) ? 'The API answered with something unexpected.' : aiErrorMessage(r.status, r.json, WHAT))
    } catch (e) { setRunErr(errText(e, `Could not reach the ${WHAT}`)) } finally { busy.current = false; setRunning(null) }
  }

  return (
    <>
      <p className="muted" data-testid="evals-dry-note">Eval runs are dry: every case runs its agent in suggest mode, so nothing is executed and no data changes. A run still makes real gateway calls, which count against the AI budget.</p>
      <div><button type="button" className="outline" onClick={() => setRefresh((n) => n + 1)} data-testid="evals-refresh">Refresh</button></div>

      <div className="stack">
        <h2>Suites</h2>
        {runErr && <p role="alert" className="error-text" data-testid="eval-run-error">{runErr}</p>}
        <State l={suites} id="suites" empty={(v) => v.length === 0} emptyText="This project defines no eval suites.">
          {(v) => (
            <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Eval suites">
              <table className="stage-table" data-testid="suites-table">
                <caption className="sr-only">Eval suites and their latest result</caption>
                <thead><tr><th scope="col">Suite</th><th scope="col">Agent</th><th scope="col">Cases</th><th scope="col">Pass mark</th><th scope="col">Latest</th><th scope="col">Run</th></tr></thead>
                <tbody>{v.map((s) => (
                  <tr key={s.name} data-testid="suite-row">
                    <th scope="row">{s.name}</th><td>{s.agent}</td><td className="num">{s.case_count}</td><td>{bpText(s.pass_bp)}</td>
                    <td>{s.latest ? `${s.latest.passed ? 'Passed' : 'Failed'} at ${bpText(s.latest.score_bp)} (${s.latest.created_at})` : 'Never run'}</td>
                    <td><button type="button" disabled={running !== null} aria-label={`Run suite ${s.name} (dry)`} onClick={() => void run(s.name)} data-testid="suite-run">{running === s.name ? 'Running…' : 'Run (dry)'}</button></td>
                  </tr>))}</tbody>
              </table>
            </div>
          )}
        </State>
        {fresh && <div data-testid="eval-fresh"><h3>Result of the run you just started</h3><RunDetail run={fresh} /></div>}
      </div>

      <div className="stack">
        <h2>Runs</h2>
        <div className="hstack">
          <label htmlFor={filterId}>Suite</label>
          <input id={filterId} value={suiteFilter} maxLength={40} onChange={(e) => { setSuiteFilter(e.target.value); setOffset(0) }} data-testid="runs-suite" />
        </div>
        <State l={runs} id="runs" empty={(v) => v.items.length === 0} emptyText="No eval runs yet.">
          {(v) => (
            <>
              <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Eval runs">
                <table className="stage-table" data-testid="runs-table">
                  <caption className="sr-only">Eval runs, newest first</caption>
                  <thead><tr><th scope="col">When</th><th scope="col">Suite</th><th scope="col">Score</th><th scope="col">Verdict</th><th scope="col">Cases</th><th scope="col">By</th><th scope="col">Detail</th></tr></thead>
                  <tbody>{v.items.map((r) => (
                    <tr key={r.id} data-testid="run-row">
                      <td>{r.created_at}</td><th scope="row">{r.suite}</th><td>{bpText(r.score_bp)}</td><td>{r.passed ? 'Passed' : 'Failed'}</td><td className="num">{r.passed_count}/{r.total}</td><td>{shortId(r.created_by)}</td>
                      <td><button type="button" className="outline small" aria-label={`Show run of ${r.suite} from ${r.created_at}`} onClick={() => { setSelected(r.id); setFresh(null) }} data-testid="run-open">Show</button></td>
                    </tr>))}</tbody>
                </table>
              </div>
              <Pager id="runs" info={pageInfo(Number(v.total), LIMIT, offset)} onPrev={() => setOffset(Math.max(0, offset - LIMIT))} onNext={() => setOffset(offset + LIMIT)} />
            </>
          )}
        </State>
      </div>

      {selected && (
        <div className="stack">
          <h2>Run detail</h2>
          <State l={detail} id="run-detail" empty={() => false} emptyText="">{(r) => <RunDetail run={r} />}</State>
        </div>
      )}
    </>
  )
}

export function EvalsPage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  return (
    <AiPageFrame projectId={projectId} session={session} testid="evals-page" title="AI evals"
      intro="Check an agent against a suite of test cases before you let it act on its own.">
      {(s) => <Body session={s} />}
    </AiPageFrame>
  )
}
