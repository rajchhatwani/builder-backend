import { useEffect, useId, useState } from 'react'
import type { PreviewSession } from '../preview/previewSession'
import { MATCH_STATES, STATE_LABEL, llComplete, parseBatchRequests, parseCandidates, toPt, type CandidateBody, type LL } from './opsLogic'
import { Confirm, Feedback, OpsPage, PointInput, State, isPage, must, useAction, useCall, useGet, type Call, type Page } from './opsShared'

interface Assignment { id: string; request_ref: string; candidate_id: string; status: string; score: number; distance_m: number; offered_at: string; expires_at: string; decided_at: string | null }
interface Ranked { candidate_id: string; score: number; distance_m: number; parts: { distance: number; load: number; rating: number } }
interface RankOut { items: Ranked[]; excluded: { candidate_id: string; reason: string }[] }
interface BatchOut { pairs: { request_ref: string; candidate_id: string; score: number; distance_m: number }[]; unassigned: string[]; skipped: string[]; total_score: number; solver: string; assignments: Assignment[] }
const CAND_HELP = 'One candidate per line: id, lat, lng, load, rating (thousandths, 0-5000). Latitude and longitude go together; load and rating are optional.'

function Solve({ call, onAssigned }: { call: Call; onAssigned: () => void }) {
  const id = useId()
  const [ref, setRef] = useState('')
  const [point, setPoint] = useState<LL>({ lat: null, lng: null })
  const [cands, setCands] = useState('')
  const [reqs, setReqs] = useState('')
  const [commit, setCommit] = useState(false)
  const [confirm, setConfirm] = useState<'assign' | 'batch' | null>(null)
  const [rank, setRank] = useState<RankOut | null>(null)
  const [batch, setBatch] = useState<BatchOut | null>(null)
  const a = useAction()

  const candidates = (): CandidateBody[] | null => {
    const c = parseCandidates(cands)
    if (!c.ok) { a.fail(c.error); return null }
    return c.items
  }
  async function doRank() {
    const p = toPt(point), c = candidates()
    if (!c) return
    if (!p) { a.fail('Enter the request point (latitude and longitude).'); return }
    setRank(null)
    await a.run(async () => { setRank((await must(call, 'POST', '/matching/rank', { point: p, candidates: c }, 'matching')) as RankOut) })
  }
  async function doAssign() {
    const p = toPt(point), c = candidates()
    if (!c) return
    if (!p) { a.fail('Enter the request point (latitude and longitude).'); return }
    if (!ref.trim()) { a.fail('Give the request a reference.'); return }
    await a.run(async () => {
      const j = (await must(call, 'POST', '/matching/assignments', { request_ref: ref.trim(), point: p, candidates: c }, 'matching')) as Assignment
      onAssigned()
      return `Offered to ${j.candidate_id} (score ${j.score}, ${j.distance_m} m).`
    })
    setConfirm(null)
  }
  async function doBatch() {
    const r = parseBatchRequests(reqs), c = candidates()
    if (!r.ok) { a.fail(r.error); return }
    if (!c) return
    setBatch(null)
    await a.run(async () => {
      const j = (await must(call, 'POST', '/matching/batch', { requests: r.items, candidates: c, commit }, 'matching')) as BatchOut
      setBatch(j)
      if (commit) onAssigned()
      return commit ? `${j.assignments.length} assignment(s) created.` : 'Preview only; nothing was assigned.'
    })
    setConfirm(null)
  }
  const askBatch = () => {
    const r = parseBatchRequests(reqs), c = parseCandidates(cands)
    if (!r.ok) { a.fail(r.error); return }
    if (!c.ok) { a.fail(c.error); return }
    if (commit) { a.clear(); setConfirm('batch') } else void doBatch()
  }

  return (
    <div className="stack" data-testid="solve-section">
      <h2>Rank, assign and batch solve</h2>
      <div className="stack">
        <h3>Candidates</h3>
        <label htmlFor={`${id}-c`}>Candidates (shared by the forms below)</label>
        <textarea id={`${id}-c`} rows={4} value={cands} spellCheck={false} aria-describedby={`${id}-ch`} data-testid="cands" placeholder="van-1, 40.0, -74.0, 2, 4500" onChange={(e) => setCands(e.target.value)} />
        <small id={`${id}-ch`} className="muted">{CAND_HELP}</small>
      </div>
      <form className="stack" aria-labelledby={`${id}-rh`} data-testid="rank-form" onSubmit={(e) => e.preventDefault()}>
        <h3 id={`${id}-rh`}>One request</h3>
        <div className="hstack">
          <label htmlFor={`${id}-ref`}>Request reference</label>
          <input id={`${id}-ref`} value={ref} maxLength={128} data-testid="request-ref" onChange={(e) => setRef(e.target.value)} />
        </div>
        <PointInput legend="Request point" testid="request-point" value={point} onChange={setPoint} />
        <div className="hstack">
          <button type="button" className="outline" disabled={a.busy} onClick={() => void doRank()} data-testid="rank-run">Rank candidates</button>
          <button type="button" disabled={a.busy} onClick={() => { a.clear(); const c = parseCandidates(cands); if (!c.ok) a.fail(c.error); else if (!llComplete(point)) a.fail('Enter the request point (latitude and longitude).'); else if (!ref.trim()) a.fail('Give the request a reference.'); else setConfirm('assign') }} data-testid="assign-run">Assign best candidate</button>
        </div>
      </form>
      {rank && (
        <div className="stack" data-testid="rank-result">
          {rank.items.length === 0 ? <p className="muted" data-testid="rank-empty">No candidate is eligible.</p> : (
            <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Ranked candidates">
              <table className="stage-table" data-testid="rank-table">
                <caption className="sr-only">Candidates, best first</caption>
                <thead><tr><th scope="col">Candidate</th><th scope="col">Score</th><th scope="col">Distance (m)</th><th scope="col">Distance part</th><th scope="col">Load part</th><th scope="col">Rating part</th></tr></thead>
                <tbody>{rank.items.map((r) => <tr key={r.candidate_id} data-testid="rank-row"><th scope="row">{r.candidate_id}</th><td className="num">{r.score}</td><td className="num">{r.distance_m}</td><td className="num">{r.parts.distance}</td><td className="num">{r.parts.load}</td><td className="num">{r.parts.rating}</td></tr>)}</tbody>
              </table>
            </div>
          )}
          {rank.excluded.length > 0 && <p data-testid="rank-excluded">Excluded: {rank.excluded.map((x) => `${x.candidate_id} (${x.reason})`).join(', ')}</p>}
        </div>
      )}
      {confirm === 'assign' && <Confirm testid="assign-confirm" busy={a.busy} yes="Yes, assign" text={`Offer request ${ref.trim()} to the best-ranked candidate? Only one active assignment per request is allowed.`} onYes={() => void doAssign()} onNo={() => setConfirm(null)} />}

      <form className="stack" aria-labelledby={`${id}-bh`} data-testid="batch-form" onSubmit={(e) => { e.preventDefault(); askBatch() }}>
        <h3 id={`${id}-bh`}>Batch solve</h3>
        <label htmlFor={`${id}-rq`}>Requests</label>
        <textarea id={`${id}-rq`} rows={3} value={reqs} spellCheck={false} data-testid="batch-requests" placeholder="R-1, 40.01, -74.0" aria-describedby={`${id}-rqh`} onChange={(e) => setReqs(e.target.value)} />
        <small id={`${id}-rqh`} className="muted">One request per line: reference, lat, lng.</small>
        <div className="hstack">
          <input id={`${id}-cm`} type="checkbox" checked={commit} data-testid="batch-commit" onChange={(e) => setCommit(e.target.checked)} />
          <label htmlFor={`${id}-cm`}>Create the assignments (otherwise only preview the solution)</label>
        </div>
        <div><button type="submit" disabled={a.busy} data-testid="batch-run">{commit ? 'Solve and assign' : 'Preview solution'}</button></div>
      </form>
      {confirm === 'batch' && <Confirm testid="batch-confirm" busy={a.busy} yes="Yes, assign all" text="Create an assignment for every solved pair?" onYes={() => void doBatch()} onNo={() => setConfirm(null)} />}
      <Feedback a={a} id="solve" />
      {batch && (
        <div className="stack" data-testid="batch-result">
          <p>Solver: {batch.solver}. Total score {batch.total_score}. {batch.pairs.length} pair(s), {batch.unassigned.length} unassigned{batch.skipped.length ? `, ${batch.skipped.length} skipped` : ''}.</p>
          {batch.pairs.length > 0 && (
            <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Batch pairs">
              <table className="stage-table" data-testid="batch-table">
                <caption className="sr-only">Solved request and candidate pairs</caption>
                <thead><tr><th scope="col">Request</th><th scope="col">Candidate</th><th scope="col">Score</th><th scope="col">Distance (m)</th></tr></thead>
                <tbody>{batch.pairs.map((p) => <tr key={p.request_ref} data-testid="batch-row"><th scope="row">{p.request_ref}</th><td>{p.candidate_id}</td><td className="num">{p.score}</td><td className="num">{p.distance_m}</td></tr>)}</tbody>
              </table>
            </div>
          )}
          {batch.unassigned.length > 0 && <p data-testid="batch-unassigned">Unassigned: {batch.unassigned.join(', ')}</p>}
        </div>
      )}
    </div>
  )
}

function Assignments({ call, refresh }: { call: Call; refresh: number }) {
  const id = useId()
  const [status, setStatus] = useState('')
  const [list, reload] = useGet<Page<Assignment>>(call, `/matching/assignments?limit=100&offset=0${status ? `&status=${status}` : ''}`, 'matching')
  useEffect(() => { if (refresh > 0) reload() }, [refresh, reload])
  const [confirmDue, setConfirmDue] = useState(false)
  const a = useAction()

  async function act(row: Assignment, verb: 'accept' | 'reject' | 'expire') {
    if (await a.run(async () => {
      await must(call, 'POST', `/matching/assignments/${row.id}/${verb}`, undefined, 'matching')
      return `${row.request_ref}: ${verb === 'accept' ? 'accepted' : verb === 'reject' ? 'rejected' : 'expired'}.`
    })) reload()
  }
  async function expireDue() {
    const ok = await a.run(async () => {
      const j = (await must(call, 'POST', '/matching/expire-due', undefined, 'matching')) as { expired?: number }
      return `${j.expired ?? 0} overdue offer(s) expired.`
    })
    setConfirmDue(false)
    if (ok) reload()
  }

  return (
    <div className="stack" data-testid="assignments-section">
      <h2>Assignments</h2>
      <div className="hstack">
        <label htmlFor={`${id}-st`}>State</label>
        <select id={`${id}-st`} value={status} data-testid="assignment-filter" onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>{MATCH_STATES.map((s) => <option key={s} value={s}>{STATE_LABEL[s]}</option>)}
        </select>
        <button type="button" className="outline" onClick={reload} data-testid="assignments-refresh">Refresh</button>
        <button type="button" className="outline" disabled={a.busy} onClick={() => { a.clear(); setConfirmDue(true) }} data-testid="expire-due">Expire due</button>
      </div>
      {confirmDue && <Confirm testid="expire-due-confirm" busy={a.busy} yes="Yes, expire overdue offers" text="Expire every offer whose time has run out? Expired offers cannot be accepted any more." onYes={() => void expireDue()} onNo={() => setConfirmDue(false)} />}
      <Feedback a={a} id="assignment" />
      <State l={list} id="assignments" empty={(v) => !isPage(v) || v.items.length === 0} emptyText={status ? `No ${STATE_LABEL[status].toLowerCase()} assignments.` : 'No assignments yet.'}>
        {(v) => (
          <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Assignments">
            <table className="stage-table" data-testid="assignment-table">
              <caption className="sr-only">Assignments, newest first</caption>
              <thead><tr><th scope="col">Request</th><th scope="col">Candidate</th><th scope="col">State</th><th scope="col">Score</th><th scope="col">Distance (m)</th><th scope="col">Expires</th><th scope="col">Actions</th></tr></thead>
              <tbody>{v.items.map((r) => (
                <tr key={r.id} data-testid="assignment-row">
                  <th scope="row">{r.request_ref}</th><td>{r.candidate_id}</td><td data-testid="assignment-state">{STATE_LABEL[r.status] ?? r.status}</td><td className="num">{r.score}</td><td className="num">{r.distance_m}</td><td>{r.expires_at}</td>
                  <td className="hstack">{r.status === 'offered' ? (
                    <>
                      <button type="button" className="outline" disabled={a.busy} aria-label={`Accept ${r.request_ref}`} data-testid="assignment-accept" onClick={() => void act(r, 'accept')}>Accept</button>
                      <button type="button" className="outline" disabled={a.busy} aria-label={`Reject ${r.request_ref}`} data-testid="assignment-reject" onClick={() => void act(r, 'reject')}>Reject</button>
                      <button type="button" className="outline" disabled={a.busy} aria-label={`Expire ${r.request_ref}`} data-testid="assignment-expire" onClick={() => void act(r, 'expire')}>Expire</button>
                    </>
                  ) : <span className="muted">Decided</span>}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        )}
      </State>
    </div>
  )
}

function Body({ session }: { session: PreviewSession }) {
  const call = useCall(session)
  const [n, setN] = useState(0)
  return (<><Solve call={call} onAssigned={() => setN((x) => x + 1)} /><Assignments call={call} refresh={n} /></>)
}

export function MatchingPage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  return (
    <OpsPage projectId={projectId} session={session} testid="matching-page" title="Matching"
      intro="Rank candidates for a request, offer it to the best one, solve a batch, and decide the offers (accept, reject or expire).">
      {(s) => <Body key={projectId} session={s} />}
    </OpsPage>
  )
}
