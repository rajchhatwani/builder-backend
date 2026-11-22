import { useCallback, useEffect, useId, useState } from 'react'
import { PreviewSessionGate } from '../preview/PreviewSessionGate'
import { usePreviewSession } from '../preview/usePreviewSession'
import type { PreviewSession } from '../preview/previewSession'
import { defaultExponent, formatMinor, moneyErrorMessage, newIdempotencyKey, parseStatementCsv, type Minor } from './moneyLogic'
import { State, UNEXPECTED, errText, isPage, ok2xx, useCall, type Call, type Load, type Page } from './moneyShared'

interface Summary { currency: string; line_count: number; matched_count: number; unmatched_line_count: number; unmatched_entry_count: number; statement_total_minor: Minor; matched_diff_minor: Minor; unmatched_lines_minor: Minor; unmatched_entries_minor: Minor; difference_minor: Minor }
interface Run { id: string; account_id: string; currency: string; name: string | null; period_start: string | null; period_end: string | null; status: string; line_count: number; matched_count: number; summary: Summary | null }
interface Line { id: string; line_no: number; external_id: string; date: string; amount_minor: Minor; currency: string; reference: string | null }
interface EntryRef { id: string; date: string; amount_minor: Minor; reference: string | null; description: string | null }
interface Pair { match: { id: string; method: string; diff_minor: Minor }; line: Line; entry: EntryRef }
interface Results { run: Run; matched: Pair[]; matched_total: number; unmatched_lines: Line[]; unmatched_entries: EntryRef[]; entries_truncated: boolean; summary: Summary }
interface Account { id: string; code: string; name: string; currency: string; exponent: number }
const isResults = (j: unknown): j is Results => !!j && typeof j === 'object' && Array.isArray((j as { matched?: unknown }).matched) && !!(j as { summary?: unknown }).summary

function ReconciliationBody({ session }: { projectId: string; session: PreviewSession }) {
  const call = useCall(session)
  const [runs, setRuns] = useState<Load<Page<Run>>>({ s: 'idle' })
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [sel, setSel] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let dead = false
    setRuns({ s: 'loading' })
    void (async () => {
      try {
        const [r, a] = await Promise.all([call('GET', '/reconciliation/runs?limit=100&offset=0'), call('GET', '/ledger/accounts?limit=200&offset=0')])
        if (dead) return
        if (ok2xx(a.status) && isPage(a.json)) setAccounts(a.json.items as Account[])
        setRuns(ok2xx(r.status) ? (isPage(r.json) ? { s: 'ok', v: r.json as Page<Run> } : { s: 'error', m: UNEXPECTED }) : { s: 'error', m: moneyErrorMessage(r.status, r.json, 'reconciliation') })
      } catch (e) { if (!dead) setRuns({ s: 'error', m: errText(e, 'Could not reach the reconciliation API') }) }
    })()
    return () => { dead = true }
  }, [call, refresh])

  const reload = useCallback(() => setRefresh((n) => n + 1), [])

  return (
    <>
      <div><button type="button" className="outline" onClick={reload} data-testid="recon-refresh">Refresh</button></div>
      {notice && <p role="status" data-testid="recon-notice">{notice}</p>}
      <div>
        <h2>Runs</h2>
        <State l={runs} id="recon-runs" empty={(v) => v.items.length === 0} emptyText="No reconciliation runs yet. Import a statement below.">
          {(v) => (
            <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Reconciliation runs">
              <table className="stage-table" data-testid="recon-table">
                <caption className="sr-only">Reconciliation runs</caption>
                <thead><tr><th scope="col">Name</th><th scope="col">Period</th><th scope="col">Currency</th><th scope="col">Status</th><th scope="col">Matched</th><th scope="col">Open</th></tr></thead>
                <tbody>{v.items.map((r) => (
                  <tr key={r.id} data-testid="recon-run-row">
                    <th scope="row">{r.name ?? r.id}</th><td>{r.period_start ?? ''} {r.period_end ? `to ${r.period_end}` : ''}</td><td>{r.currency}</td><td>{r.status}</td><td className="num">{r.matched_count} / {r.line_count}</td>
                    <td><button type="button" className="outline small" aria-label={`Open run ${r.name ?? r.id}`} onClick={() => setSel(r.id)} data-testid="recon-open">Open</button></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </State>
      </div>

      {sel && <RunDetail key={sel} runId={sel} call={call} accounts={accounts} onChanged={reload} onNotice={setNotice} />}
      <CreateRun call={call} accounts={accounts} onCreated={(r) => { setNotice('Statement imported.'); setSel(r.id); reload() }} />
    </>
  )
}

function RunDetail({ runId, call, accounts, onChanged, onNotice }: { runId: string; call: Call; accounts: Account[] | null; onChanged: () => void; onNotice: (m: string | null) => void }) {
  const [res, setRes] = useState<Load<Results>>({ s: 'idle' })
  const [n, setN] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [lineId, setLineId] = useState('')
  const [entryId, setEntryId] = useState('')
  const [csv, setCsv] = useState('')
  const [confirmClose, setConfirmClose] = useState(false)
  const [busy, setBusy] = useState(false)
  const id = useId()

  useEffect(() => {
    let dead = false
    setRes((p) => (p.s === 'ok' ? p : { s: 'loading' }))
    void (async () => {
      try {
        const r = await call('GET', `/reconciliation/runs/${encodeURIComponent(runId)}/results?limit=200&offset=0`)
        if (dead) return
        setRes(ok2xx(r.status) ? (isResults(r.json) ? { s: 'ok', v: r.json } : { s: 'error', m: UNEXPECTED }) : { s: 'error', m: moneyErrorMessage(r.status, r.json, 'reconciliation') })
      } catch (e) { if (!dead) setRes({ s: 'error', m: errText(e, 'Could not reach the reconciliation API') }) }
    })()
    return () => { dead = true }
  }, [call, runId, n])

  async function act(method: string, path: string, body: unknown, done: string) {
    setError(null); onNotice(null); setBusy(true)
    try {
      const r = await call(method, `/reconciliation/runs/${encodeURIComponent(runId)}${path}`, body)
      if (ok2xx(r.status)) {
        onNotice(done); setConfirmClose(false); setLineId(''); setEntryId(''); setCsv(''); setN((x) => x + 1); onChanged()
        return r.json
      }
      setError(moneyErrorMessage(r.status, r.json, 'reconciliation'))
    } catch (e) { setError(errText(e, 'Could not reach the reconciliation API')) } finally { setBusy(false) }
  }

  async function addLines(run: Run) {
    const acct = accounts?.find((a) => a.id === run.account_id)
    const p = parseStatementCsv(csv, acct?.exponent ?? defaultExponent(run.currency), run.currency)
    if (!p.lines) { setError(p.error); return }
    await act('POST', '/lines', { lines: p.lines }, 'Statement lines added.')
  }

  return (
    <div data-testid="recon-detail" role="region" aria-label="Run detail">
      <State l={res} id="recon-detail-state" empty={() => false} emptyText="">
        {(v) => {
          const exp = accounts?.find((a) => a.id === v.run.account_id)?.exponent ?? defaultExponent(v.run.currency)
          const f = (m: Minor) => formatMinor(m, exp)
          const open = v.run.status === 'open'
          const s = v.summary
          return (
            <>
              <h2>Run {v.run.name ?? v.run.id} ({v.run.status})</h2>
              <ul data-testid="recon-summary">
                <li>Statement total: {s.currency} {f(s.statement_total_minor)}</li>
                <li>Matched: {s.matched_count} of {s.line_count} lines (difference on matched {f(s.matched_diff_minor)})</li>
                <li>Unmatched statement lines: {s.unmatched_line_count} ({f(s.unmatched_lines_minor)}); unmatched ledger entries: {s.unmatched_entry_count} ({f(s.unmatched_entries_minor)})</li>
                <li data-testid="recon-difference">Difference (statement minus ledger): {f(s.difference_minor)}</li>
              </ul>
              {open && (
                <div className="hstack">
                  <button type="button" className="outline" disabled={busy} onClick={() => void act('POST', '/match', undefined, 'Auto-match finished.')} data-testid="recon-automatch">Auto-match</button>
                  <button type="button" disabled={busy} onClick={() => setConfirmClose(true)} data-testid="recon-close">Close run</button>
                </div>
              )}
              {confirmClose && (
                <div role="alertdialog" aria-label="Confirm close" className="hstack" data-testid="recon-close-confirm">
                  <span>Close this run? Closed runs cannot be changed.</span>
                  <button type="button" disabled={busy} onClick={() => void act('POST', '/close', undefined, 'Run closed.')} data-testid="recon-close-yes">Yes, close</button>
                  <button type="button" className="outline" onClick={() => setConfirmClose(false)}>Cancel</button>
                </div>
              )}
              {error && <p role="alert" className="error-text" data-testid="recon-error">{error}</p>}

              <h3>Matched ({v.matched_total})</h3>
              {v.matched.length === 0 ? <p className="muted" data-testid="recon-matched-empty">Nothing matched yet.</p> : (
                <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Matched pairs">
                  <table className="stage-table" data-testid="recon-matched">
                    <caption className="sr-only">Matched statement lines and ledger entries</caption>
                    <thead><tr><th scope="col">Statement line</th><th scope="col">Amount</th><th scope="col">Ledger entry</th><th scope="col">Amount</th><th scope="col">Method</th><th scope="col">Unmatch</th></tr></thead>
                    <tbody>{v.matched.map((p) => (
                      <tr key={p.match.id} data-testid="recon-pair">
                        <th scope="row">{p.line.external_id}</th><td className="num">{f(p.line.amount_minor)}</td><td>{p.entry.description ?? p.entry.reference ?? p.entry.id}</td><td className="num">{f(p.entry.amount_minor)}</td><td>{p.match.method}</td>
                        <td>{open && <button type="button" className="ghost small" disabled={busy} aria-label={`Unmatch ${p.line.external_id}`} onClick={() => void act('DELETE', `/matches/${encodeURIComponent(p.match.id)}`, undefined, 'Match removed.')} data-testid="recon-unmatch">Unmatch</button>}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}

              <h3>Unmatched statement lines ({v.unmatched_lines.length})</h3>
              {v.unmatched_lines.length === 0 ? <p className="muted" data-testid="recon-ul-empty">None.</p> : (
                <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Unmatched statement lines">
                  <table className="stage-table" data-testid="recon-unmatched-lines">
                    <caption className="sr-only">Unmatched statement lines</caption>
                    <thead><tr><th scope="col">External id</th><th scope="col">Date</th><th scope="col">Amount</th><th scope="col">Reference</th></tr></thead>
                    <tbody>{v.unmatched_lines.map((l) => <tr key={l.id} data-testid="recon-ul-row"><th scope="row">{l.external_id}</th><td>{l.date}</td><td className="num">{f(l.amount_minor)}</td><td>{l.reference ?? ''}</td></tr>)}</tbody>
                  </table>
                </div>
              )}

              <h3>Unmatched ledger entries ({v.unmatched_entries.length}{v.entries_truncated ? ', list truncated' : ''})</h3>
              {v.unmatched_entries.length === 0 ? <p className="muted" data-testid="recon-ue-empty">None.</p> : (
                <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Unmatched ledger entries">
                  <table className="stage-table" data-testid="recon-unmatched-entries">
                    <caption className="sr-only">Unmatched ledger entries</caption>
                    <thead><tr><th scope="col">Date</th><th scope="col">Description</th><th scope="col">Reference</th><th scope="col">Amount</th></tr></thead>
                    <tbody>{v.unmatched_entries.map((e) => <tr key={e.id} data-testid="recon-ue-row"><td>{e.date}</td><th scope="row">{e.description ?? e.id}</th><td>{e.reference ?? ''}</td><td className="num">{f(e.amount_minor)}</td></tr>)}</tbody>
                  </table>
                </div>
              )}

              {open && (
                <>
                  {v.unmatched_lines.length > 0 && v.unmatched_entries.length > 0 && (
                    <form className="hstack" aria-label="Match manually" data-testid="recon-manual" onSubmit={(e) => { e.preventDefault(); if (!lineId || !entryId) { setError('Choose a statement line and a ledger entry.'); return } void act('POST', '/matches', { line_id: lineId, entry_id: entryId }, 'Matched.') }}>
                      <label htmlFor={`${id}-l`}>Statement line</label>
                      <select id={`${id}-l`} value={lineId} onChange={(e) => setLineId(e.target.value)} data-testid="recon-pick-line"><option value="">Choose…</option>{v.unmatched_lines.map((l) => <option key={l.id} value={l.id}>{l.external_id} ({f(l.amount_minor)})</option>)}</select>
                      <label htmlFor={`${id}-e`}>Ledger entry</label>
                      <select id={`${id}-e`} value={entryId} onChange={(e) => setEntryId(e.target.value)} data-testid="recon-pick-entry"><option value="">Choose…</option>{v.unmatched_entries.map((x) => <option key={x.id} value={x.id}>{x.description ?? x.id} ({f(x.amount_minor)})</option>)}</select>
                      <button type="submit" disabled={busy} data-testid="recon-match">Match</button>
                    </form>
                  )}
                  <form className="stack" aria-label="Add statement lines" onSubmit={(e) => { e.preventDefault(); void addLines(v.run) }}>
                    <label htmlFor={`${id}-csv`}>Add statement lines (CSV: external_id,date,amount,currency,reference)</label>
                    <textarea id={`${id}-csv`} rows={3} value={csv} onChange={(e) => setCsv(e.target.value)} data-testid="recon-add-csv" />
                    <div><button type="submit" className="outline" disabled={busy} data-testid="recon-add-lines">Add lines</button></div>
                  </form>
                </>
              )}
            </>
          )
        }}
      </State>
    </div>
  )
}

function CreateRun({ call, accounts, onCreated }: { call: Call; accounts: Account[] | null; onCreated: (r: Run) => void }) {
  const id = useId()
  const [account, setAccount] = useState('')
  const [name, setName] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [csv, setCsv] = useState('')
  const [key, setKey] = useState(newIdempotencyKey)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)
    if (!account.trim()) { setError('Choose the ledger account the statement belongs to.'); return }
    const acct = accounts?.find((a) => a.id === account)
    const p = parseStatementCsv(csv, acct?.exponent ?? 2, acct?.currency ?? 'USD')
    if (!p.lines) { setError(p.error); return }
    const body: Record<string, unknown> = { idempotency_key: key, account_id: account.trim(), lines: p.lines }
    if (name) body.name = name
    if (start) body.period_start = start
    if (end) body.period_end = end
    setBusy(true)
    try {
      const r = await call('POST', '/reconciliation/runs', body)
      if (ok2xx(r.status) && r.json && typeof r.json === 'object') {
        setCsv(''); setName(''); setKey(newIdempotencyKey()); onCreated(r.json as Run)
      } else setError(moneyErrorMessage(r.status, r.json, 'reconciliation'))
    } catch (e) { setError(errText(e, 'Could not reach the reconciliation API')) } finally { setBusy(false) }
  }

  return (
    <form className="stack" aria-labelledby={`${id}-h`} data-testid="recon-create-form" onSubmit={(e) => { e.preventDefault(); void submit() }}>
      <h2 id={`${id}-h`}>Import a statement</h2>
      <div className="hstack">
        <label htmlFor={`${id}-acct`}>Ledger account</label>
        {accounts ? (
          <select id={`${id}-acct`} value={account} onChange={(e) => setAccount(e.target.value)} data-testid="recon-account">
            <option value="">Choose…</option>{accounts.map((a) => <option key={a.id} value={a.id}>{a.code} {a.name} ({a.currency})</option>)}
          </select>
        ) : <input id={`${id}-acct`} value={account} onChange={(e) => setAccount(e.target.value)} placeholder="account id" data-testid="recon-account" />}
        <label htmlFor={`${id}-name`}>Name</label><input id={`${id}-name`} value={name} maxLength={200} onChange={(e) => setName(e.target.value)} data-testid="recon-name" />
        <label htmlFor={`${id}-s`}>Period start</label><input id={`${id}-s`} type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        <label htmlFor={`${id}-e`}>Period end</label><input id={`${id}-e`} type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
      </div>
      <label htmlFor={`${id}-csv`}>Statement lines (CSV: external_id,date,amount,currency,reference; amounts signed, positive = debit side)</label>
      <textarea id={`${id}-csv`} rows={5} value={csv} onChange={(e) => setCsv(e.target.value)} data-testid="recon-csv" />
      <div className="hstack">
        <label htmlFor={`${id}-k`}>Idempotency key</label>
        <input id={`${id}-k`} value={key} maxLength={128} onChange={(e) => setKey(e.target.value)} data-testid="recon-key" />
      </div>
      {error && <p role="alert" className="error-text" data-testid="recon-create-error">{error}</p>}
      <button type="submit" disabled={busy} data-testid="recon-create">{busy ? 'Importing…' : 'Import and create run'}</button>
    </form>
  )
}

export function ReconciliationPage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  const own = usePreviewSession(projectId, { disabled: !!session })
  const s = session ?? own
  return (
    <section aria-labelledby="recon-h" data-testid="reconciliation-page" className="stack">
      <h1 id="recon-h">Reconciliation</h1>
      <p className="muted">Match bank statement lines against ledger entries. Closed runs are final.</p>
      <PreviewSessionGate session={s} prefix="recon">
        <ReconciliationBody key={projectId} projectId={projectId} session={s} />
      </PreviewSessionGate>
    </section>
  )
}
