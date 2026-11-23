import { useEffect, useId, useState } from 'react'
import type { PreviewSession } from '../preview/previewSession'
import { formatBp, formatMilli, parseFeatures, parseKind, parseWhole } from './opsLogic'
import { Feedback, OpsPage, State, isObj, isPage, must, useAction, useCall, useGet, type Call, type Page } from './opsShared'

interface Rec { id: string; kind: string; subject_ref: string; model_id: string; unit: string; value: number; low: number; high: number; features: Record<string, unknown>; actual: number | null; actual_at: string | null; created_at: string }
interface Stats { logged: number; with_actual: number; mae_milli: number | null; abs_error_sum: number; covered: number; coverage_bp: number | null }
const isStats = (j: unknown): boolean => isObj(j) && typeof (j as { logged?: unknown }).logged === 'number'

function Predict({ call, onDone }: { call: Call; onDone: () => void }) {
  const id = useId()
  const [kind, setKind] = useState('')
  const [subject, setSubject] = useState('')
  const [features, setFeatures] = useState('')
  const [last, setLast] = useState<Rec | null>(null)
  const a = useAction()
  async function submit() {
    if (!parseKind(kind)) { a.fail('Kind: 1-32 characters, letters, digits and . _ : - only, starting with a letter or digit.'); return }
    if (!subject.trim() || subject.length > 128) { a.fail('Subject reference: 1-128 characters.'); return }
    const f = parseFeatures(features)
    if (!f.ok) { a.fail(f.error); return }
    setLast(null)
    await a.run(async () => {
      const r = (await must(call, 'POST', '/prediction/predict', { kind: kind.trim(), subject_ref: subject, features: f.features }, 'prediction')) as Rec
      setLast(r); onDone()
      return 'Prediction recorded.'
    })
  }
  return (
    <form className="stack" aria-labelledby={`${id}-h`} data-testid="predict-form" onSubmit={(e) => { e.preventDefault(); void submit() }}>
      <h2 id={`${id}-h`}>Record a prediction</h2>
      <div className="hstack">
        <label htmlFor={`${id}-k`}>Kind</label>
        <input id={`${id}-k`} value={kind} maxLength={32} data-testid="predict-kind" onChange={(e) => setKind(e.target.value)} />
        <label htmlFor={`${id}-s`}>Subject reference</label>
        <input id={`${id}-s`} value={subject} maxLength={128} data-testid="predict-subject" onChange={(e) => setSubject(e.target.value)} />
      </div>
      <label htmlFor={`${id}-f`}>Features</label>
      <textarea id={`${id}-f`} rows={3} value={features} spellCheck={false} data-testid="predict-features" placeholder="distance_m = 1200" aria-describedby={`${id}-fh`} onChange={(e) => setFeatures(e.target.value)} />
      <small id={`${id}-fh`} className="muted">One feature per line as name = value. Whole numbers, true or false, or text. The deterministic fake predictor is used.</small>
      <div><button type="submit" disabled={a.busy} data-testid="predict-run">{a.busy ? 'Predicting…' : 'Predict and record'}</button></div>
      <Feedback a={a} id="predict" />
      {last && <p data-testid="predict-result">Predicted {last.value} {last.unit} (interval {last.low} to {last.high}) by {last.model_id}.</p>}
    </form>
  )
}

function ActualCell({ call, rec, onDone }: { call: Call; rec: Rec; onDone: () => void }) {
  const [v, setV] = useState('')
  const a = useAction()
  if (rec.actual !== null) return <>{rec.actual}</>
  async function go() {
    const n = parseWhole(v, -(2 ** 53), 2 ** 53)
    if (n === null) { a.fail('Enter the actual value as a whole number.'); return }
    if (await a.run(async () => { await must(call, 'POST', `/prediction/records/${rec.id}/actual`, { actual: n }, 'prediction'); return 'Saved.' })) onDone()
  }
  return (
    <form className="hstack" onSubmit={(e) => { e.preventDefault(); void go() }}>
      <input aria-label={`Actual value for ${rec.subject_ref}`} value={v} inputMode="numeric" data-testid="actual-input" onChange={(e) => setV(e.target.value)} />
      <button type="submit" className="outline" disabled={a.busy} aria-label={`Record actual for ${rec.subject_ref}`} data-testid="actual-save">Record</button>
      {a.error && <span role="alert" className="error-text" data-testid="actual-error">{a.error}</span>}
    </form>
  )
}

function Records({ call, refresh, onDone }: { call: Call; refresh: number; onDone: () => void }) {
  const id = useId()
  const [kindText, setKindText] = useState('')
  const [kind, setKind] = useState('')
  const [hasActual, setHasActual] = useState('')
  const q = [kind && `kind=${encodeURIComponent(kind)}`, hasActual && `has_actual=${hasActual}`].filter(Boolean).join('&')
  const [list, reload] = useGet<Page<Rec>>(call, `/prediction/records?limit=100&offset=0${q ? `&${q}` : ''}`, 'prediction')
  useEffect(() => { if (refresh > 0) reload() }, [refresh, reload])
  return (
    <div className="stack" data-testid="records-section">
      <h2>Records</h2>
      <form className="hstack" aria-label="Filter records" onSubmit={(e) => { e.preventDefault(); setKind(kindText.trim()) }}>
        <label htmlFor={`${id}-k`}>Kind</label>
        <input id={`${id}-k`} value={kindText} maxLength={32} data-testid="record-filter-kind" onChange={(e) => setKindText(e.target.value)} />
        <label htmlFor={`${id}-a`}>Actual</label>
        <select id={`${id}-a`} value={hasActual} data-testid="record-filter-actual" onChange={(e) => setHasActual(e.target.value)}>
          <option value="">Any</option><option value="true">Recorded</option><option value="false">Still missing</option>
        </select>
        <button type="submit" className="outline" data-testid="record-filter-apply">Filter</button>
      </form>
      <State l={list} id="records" empty={(v) => !isPage(v) || v.items.length === 0} emptyText="No predictions recorded yet.">
        {(v) => (
          <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Prediction records">
            <table className="stage-table" data-testid="record-table">
              <caption className="sr-only">Logged predictions, newest first</caption>
              <thead><tr><th scope="col">When</th><th scope="col">Kind</th><th scope="col">Subject</th><th scope="col">Predicted</th><th scope="col">Interval</th><th scope="col">Actual</th></tr></thead>
              <tbody>{v.items.map((r) => (
                <tr key={r.id} data-testid="record-row">
                  <td>{r.created_at}</td><td>{r.kind}</td><th scope="row">{r.subject_ref}</th>
                  <td className="num">{r.value} {r.unit}</td><td className="num">{r.low} to {r.high}</td>
                  <td className="num"><ActualCell call={call} rec={r} onDone={onDone} /></td>
                </tr>))}
              </tbody>
            </table>
          </div>
        )}
      </State>
    </div>
  )
}

function StatsSection({ call, refresh }: { call: Call; refresh: number }) {
  const id = useId()
  const [kindText, setKindText] = useState('')
  const [kind, setKind] = useState('')
  const [st, reload] = useGet<Stats>(call, `/prediction/stats${kind ? `?kind=${encodeURIComponent(kind)}` : ''}`, 'prediction', isStats)
  useEffect(() => { if (refresh > 0) reload() }, [refresh, reload])
  return (
    <div className="stack" data-testid="stats-section">
      <h2>Accuracy</h2>
      <form className="hstack" aria-label="Filter statistics" onSubmit={(e) => { e.preventDefault(); setKind(kindText.trim()) }}>
        <label htmlFor={`${id}-k`}>Kind</label>
        <input id={`${id}-k`} value={kindText} maxLength={32} data-testid="stats-kind" onChange={(e) => setKindText(e.target.value)} />
        <button type="submit" className="outline" data-testid="stats-apply">Apply</button>
      </form>
      <State l={st} id="stats" empty={(v) => v.logged === 0} emptyText="Nothing logged yet, so there are no statistics.">
        {(v) => (
          <dl className="stack" data-testid="stats">
            <div><dt>Predictions logged</dt><dd data-testid="stat-logged">{v.logged}</dd></div>
            <div><dt>With an actual value</dt><dd data-testid="stat-with-actual">{v.with_actual}</dd></div>
            <div><dt>Mean absolute error</dt><dd data-testid="stat-mae">{formatMilli(v.mae_milli)}</dd></div>
            <div><dt>Interval coverage</dt><dd data-testid="stat-coverage">{formatBp(v.coverage_bp)}{v.with_actual > 0 ? ` (${v.covered} of ${v.with_actual})` : ''}</dd></div>
          </dl>
        )}
      </State>
    </div>
  )
}

function Body({ session }: { session: PreviewSession }) {
  const call = useCall(session)
  const [n, setN] = useState(0)
  const bump = () => setN((x) => x + 1)
  return (<><Predict call={call} onDone={bump} /><Records call={call} refresh={n} onDone={bump} /><StatsSection call={call} refresh={n} /></>)
}

export function PredictionPage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  return (
    <OpsPage projectId={projectId} session={session} testid="prediction-page" title="Prediction"
      intro="Record predictions from the deterministic fake predictor, add the actual outcome later and watch the error and interval coverage.">
      {(s) => <Body key={projectId} session={s} />}
    </OpsPage>
  )
}
