import { Fragment, useCallback, useEffect, useId, useState } from 'react'
import { PreviewSessionGate } from '../preview/PreviewSessionGate'
import { usePreviewSession } from '../preview/usePreviewSession'
import type { PreviewSession } from '../preview/previewSession'
import {
  buildInvoiceLines, defaultExponent, formatMinor, invoiceTotals, moneyErrorMessage, newIdempotencyKey, parseMajor, MAX_SAFE,
  type DraftInvLine, type Invoice, type Minor,
} from './moneyLogic'
import { State, UNEXPECTED, errText, isPage, ok2xx, useCall, type Call, type Load, type Page } from './moneyShared'

const LIMIT = 100
interface AgingBucket { label: string; from_days: number; to_days: number | null; amount_minor: Minor; count: number }
interface AgingCur { currency: string; current_minor: Minor; current_count: number; buckets: AgingBucket[]; total_minor: Minor; count: number }
interface Aging { kind: string; as_of: string; bucket_days: number[]; currencies: AgingCur[] }
const isAging = (j: unknown): j is Aging => !!j && typeof j === 'object' && Array.isArray((j as { currencies?: unknown }).currencies)
const KINDS = ['receivable', 'payable'] as const
const STATUSES = ['', 'draft', 'issued', 'partially_paid', 'paid', 'void']

function InvoicesPageBody({ session }: { projectId: string; session: PreviewSession }) {
  const call = useCall(session)
  const [kind, setKind] = useState<string>('')
  const [status, setStatus] = useState('')
  const [list, setList] = useState<Load<Page<Invoice>>>({ s: 'idle' })
  const [refresh, setRefresh] = useState(0)
  const [agingKind, setAgingKind] = useState<'receivable' | 'payable'>('receivable')
  const [asOf, setAsOf] = useState('')
  const [aging, setAging] = useState<Load<Aging>>({ s: 'idle' })
  const [pay, setPay] = useState<string | null>(null)
  const [voiding, setVoiding] = useState<string | null>(null)
  const [rowError, setRowError] = useState<{ id: string; m: string } | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const kindId = useId(), statusId = useId(), agKindId = useId(), asOfId = useId()

  useEffect(() => {
    let dead = false
    setList({ s: 'loading' })
    const qs = new URLSearchParams({ limit: String(LIMIT), offset: '0' })
    if (kind) qs.set('kind', kind)
    if (status) qs.set('status', status)
    void (async () => {
      try {
        const r = await call('GET', `/invoices?${qs}`)
        if (dead) return
        setList(ok2xx(r.status) ? (isPage(r.json) ? { s: 'ok', v: r.json as Page<Invoice> } : { s: 'error', m: UNEXPECTED }) : { s: 'error', m: moneyErrorMessage(r.status, r.json) })
      } catch (e) { if (!dead) setList({ s: 'error', m: errText(e, 'Could not reach the invoicing API') }) }
    })()
    return () => { dead = true }
  }, [call, kind, status, refresh])

  useEffect(() => {
    let dead = false
    setAging({ s: 'loading' })
    const qs = new URLSearchParams({ kind: agingKind })
    if (asOf) qs.set('as_of', asOf)
    void (async () => {
      try {
        const r = await call('GET', `/invoices/aging?${qs}`)
        if (dead) return
        setAging(ok2xx(r.status) ? (isAging(r.json) ? { s: 'ok', v: r.json } : { s: 'error', m: UNEXPECTED }) : { s: 'error', m: moneyErrorMessage(r.status, r.json) })
      } catch (e) { if (!dead) setAging({ s: 'error', m: errText(e, 'Could not reach the invoicing API') }) }
    })()
    return () => { dead = true }
  }, [call, agingKind, asOf, refresh])

  const reload = useCallback(() => setRefresh((n) => n + 1), [])

  async function act(inv: Invoice, path: string, body: unknown, done: string) {
    setRowError(null); setNotice(null)
    try {
      const r = await call('POST', `/invoices/${encodeURIComponent(inv.id)}/${path}`, body)
      if (ok2xx(r.status)) { setNotice(done); setPay(null); setVoiding(null); reload(); return }
      setRowError({ id: inv.id, m: moneyErrorMessage(r.status, r.json) })
    } catch (e) { setRowError({ id: inv.id, m: errText(e, 'Could not reach the invoicing API') }) }
  }

  return (
    <>
      <div className="hstack">
        <label htmlFor={kindId}>Kind</label>
        <select id={kindId} value={kind} onChange={(e) => setKind(e.target.value)} data-testid="inv-filter-kind">
          <option value="">All</option>{KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <label htmlFor={statusId}>Status</label>
        <select id={statusId} value={status} onChange={(e) => setStatus(e.target.value)} data-testid="inv-filter-status">
          {STATUSES.map((s) => <option key={s} value={s}>{s || 'All'}</option>)}
        </select>
        <button type="button" className="outline" onClick={reload} data-testid="inv-refresh">Refresh</button>
      </div>
      {notice && <p role="status" data-testid="inv-notice">{notice}</p>}

      <div>
        <h2>Invoices</h2>
        <State l={list} id="inv-list" empty={(v) => v.items.length === 0} emptyText="No invoices yet. Create one below.">
          {(v) => (
            <>
              <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Invoices">
                <table className="stage-table" data-testid="inv-table">
                  <caption className="sr-only">Invoices</caption>
                  <thead><tr><th scope="col">Number</th><th scope="col">Kind</th><th scope="col">Counterparty</th><th scope="col">Status</th><th scope="col">Due</th><th scope="col">Total</th><th scope="col">Paid</th><th scope="col">Outstanding</th><th scope="col">Actions</th></tr></thead>
                  <tbody>{v.items.map((i) => (
                    <Fragment key={i.id}>
                      <tr data-testid="inv-row">
                        <th scope="row">{i.number ?? 'Draft'}</th><td>{i.kind}</td><td>{i.counterparty}</td><td data-testid="inv-status">{i.status}</td><td>{i.due_date ?? ''}</td>
                        <td className="num">{i.currency} {formatMinor(i.total_minor, i.exponent)}</td>
                        <td className="num">{formatMinor(i.paid_minor, i.exponent)}</td>
                        <td className="num">{formatMinor(i.outstanding_minor, i.exponent)}</td>
                        <td>
                          {i.status === 'draft' && <button type="button" className="outline small" aria-label={`Issue invoice ${i.counterparty}`} onClick={() => void act(i, 'issue', undefined, 'Invoice issued.')} data-testid="inv-issue">Issue</button>}
                          {(i.status === 'issued' || i.status === 'partially_paid') && <button type="button" className="outline small" aria-label={`Record payment for ${i.number ?? i.counterparty}`} onClick={() => { setPay(i.id); setVoiding(null); setRowError(null) }} data-testid="inv-pay-btn">Record payment</button>}
                          {(i.status === 'draft' || i.status === 'issued') && <button type="button" className="ghost small" aria-label={`Void invoice ${i.number ?? i.counterparty}`} onClick={() => { setVoiding(i.id); setPay(null); setRowError(null) }} data-testid="inv-void-btn">Void</button>}
                        </td>
                      </tr>
                      {(pay === i.id || voiding === i.id || rowError?.id === i.id) && (
                        <tr data-testid="inv-action-row">
                          <td colSpan={9}>
                            {pay === i.id && <PaymentForm inv={i} onSubmit={(b) => act(i, 'payments', b, 'Payment recorded.')} onCancel={() => setPay(null)} />}
                            {voiding === i.id && <VoidForm onSubmit={(reason) => act(i, 'void', reason ? { reason } : {}, 'Invoice voided.')} onCancel={() => setVoiding(null)} />}
                            {rowError?.id === i.id && <p role="alert" className="error-text" data-testid="inv-row-error">{rowError.m}</p>}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}</tbody>
                  <tfoot>{invoiceTotals(v.items).map((t) => (
                    <tr key={t.currency} data-testid="inv-total-row">
                      <th scope="row">Total {t.currency}</th><td /><td /><td /><td />
                      <td className="num" data-testid="inv-total-total">{formatMinor(t.total, t.exponent)}</td>
                      <td className="num" data-testid="inv-total-paid">{formatMinor(t.paid, t.exponent)}</td>
                      <td className="num" data-testid="inv-total-outstanding">{formatMinor(t.outstanding, t.exponent)}</td><td />
                    </tr>
                  ))}</tfoot>
                </table>
              </div>
              <p className="small-text muted">Showing {v.items.length} of {v.total} invoices; totals cover the rows shown and never mix currencies.</p>
            </>
          )}
        </State>
      </div>

      <div>
        <h2>Aging</h2>
        <div className="hstack">
          <label htmlFor={agKindId}>Aging for</label>
          <select id={agKindId} value={agingKind} onChange={(e) => setAgingKind(e.target.value as 'receivable' | 'payable')} data-testid="aging-kind">
            <option value="receivable">Receivable (AR)</option><option value="payable">Payable (AP)</option>
          </select>
          <label htmlFor={asOfId}>As of</label>
          <input id={asOfId} type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} data-testid="aging-asof" />
        </div>
        <State l={aging} id="aging" empty={(v) => v.currencies.length === 0} emptyText="Nothing outstanding.">
          {(v) => (
            <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Aging">
              <table className="stage-table" data-testid="aging-table">
                <caption className="sr-only">{v.kind} aging as of {v.as_of}, per currency</caption>
                <thead><tr><th scope="col">Currency</th><th scope="col">Current</th>{(v.currencies[0]?.buckets ?? []).map((b) => <th scope="col" key={b.label}>{b.label}</th>)}<th scope="col">Total</th></tr></thead>
                <tbody>{v.currencies.map((c) => {
                  const exp = defaultExponent(c.currency)
                  return (
                    <tr key={c.currency} data-testid="aging-row">
                      <th scope="row">{c.currency}</th>
                      <td className="num">{formatMinor(c.current_minor, exp)} ({c.current_count})</td>
                      {c.buckets.map((b) => <td className="num" key={b.label} data-testid="aging-bucket">{formatMinor(b.amount_minor, exp)} ({b.count})</td>)}
                      <td className="num" data-testid="aging-total">{formatMinor(c.total_minor, exp)} ({c.count})</td>
                    </tr>
                  )
                })}</tbody>
              </table>
            </div>
          )}
        </State>
      </div>

      <CreateForm call={call} onCreated={reload} />
    </>
  )
}

function PaymentForm({ inv, onSubmit, onCancel }: { inv: Invoice; onSubmit: (b: Record<string, unknown>) => Promise<void>; onCancel: () => void }) {
  const id = useId()
  const [amount, setAmount] = useState('')
  const [paidOn, setPaidOn] = useState('')
  const [ref, setRef] = useState('')
  const [key, setKey] = useState(newIdempotencyKey)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function go() {
    const m = parseMajor(amount, inv.exponent)
    if (m === null || m < 1n) { setErr(`Enter a positive amount with at most ${inv.exponent} decimals.`); return }
    if (m > MAX_SAFE) { setErr('The amount is too large.'); return }
    setErr(null); setBusy(true)
    const b: Record<string, unknown> = { idempotency_key: key, amount_minor: Number(m) }
    if (paidOn) b.paid_on = paidOn
    if (ref) b.reference = ref
    try { await onSubmit(b) } finally { setBusy(false) }
  }
  return (
    <form className="hstack" data-testid="inv-pay-form" onSubmit={(e) => { e.preventDefault(); void go() }}>
      <label htmlFor={`${id}-a`}>Amount ({inv.currency}, outstanding {formatMinor(inv.outstanding_minor, inv.exponent)})</label>
      <input id={`${id}-a`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} data-testid="inv-pay-amount" />
      <label htmlFor={`${id}-d`}>Paid on</label>
      <input id={`${id}-d`} type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
      <label htmlFor={`${id}-r`}>Reference</label>
      <input id={`${id}-r`} value={ref} maxLength={128} onChange={(e) => setRef(e.target.value)} />
      <label htmlFor={`${id}-k`}>Idempotency key</label>
      <input id={`${id}-k`} value={key} maxLength={128} onChange={(e) => setKey(e.target.value)} data-testid="inv-pay-key" />
      <button type="submit" disabled={busy} data-testid="inv-pay-submit">{busy ? 'Recording…' : 'Record payment'}</button>
      <button type="button" className="outline" onClick={onCancel}>Cancel</button>
      {err && <p role="alert" className="error-text" data-testid="inv-pay-error">{err}</p>}
    </form>
  )
}

function VoidForm({ onSubmit, onCancel }: { onSubmit: (reason: string) => Promise<void>; onCancel: () => void }) {
  const id = useId()
  const [reason, setReason] = useState('')
  return (
    <div role="alertdialog" aria-label="Confirm void" className="hstack" data-testid="inv-void-confirm">
      <span>Void this invoice? Its ledger posting is reversed. This cannot be undone.</span>
      <label htmlFor={id}>Reason</label>
      <input id={id} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} data-testid="inv-void-reason" />
      <button type="button" onClick={() => void onSubmit(reason)} data-testid="inv-void-yes">Yes, void</button>
      <button type="button" className="outline" onClick={onCancel}>Cancel</button>
    </div>
  )
}

function CreateForm({ call, onCreated }: { call: Call; onCreated: () => void }) {
  const id = useId()
  const blank = (): DraftInvLine => ({ description: '', quantity: '1', unitPrice: '', taxRate: '' })
  const [kind, setKind] = useState<'receivable' | 'payable'>('receivable')
  const [counterparty, setCounterparty] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [issue, setIssue] = useState('')
  const [due, setDue] = useState('')
  const [notes, setNotes] = useState('')
  const [lines, setLines] = useState<DraftInvLine[]>([blank()])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const set = (i: number, p: Partial<DraftInvLine>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...p } : l)))

  async function submit() {
    setError(null); setOk(null)
    const cur = currency.trim().toUpperCase()
    if (!counterparty.trim()) { setError('Enter the customer or supplier name.'); return }
    if (!/^[A-Z]{3}$/.test(cur)) { setError('Currency must be 3 letters, for example USD.'); return }
    const built = buildInvoiceLines(lines, defaultExponent(cur))
    if (!built.lines) { setError(built.error); return }
    const body: Record<string, unknown> = { kind, counterparty: counterparty.trim(), currency: cur, lines: built.lines }
    if (issue) body.issue_date = issue
    if (due) body.due_date = due
    if (notes) body.notes = notes
    setBusy(true)
    try {
      const r = await call('POST', '/invoices', body)
      if (ok2xx(r.status)) {
        setOk('Draft invoice created. Issue it from the list.')
        setCounterparty(''); setLines([blank()]); setNotes(''); setIssue(''); setDue('')
        onCreated()
      } else setError(moneyErrorMessage(r.status, r.json))
    } catch (e) { setError(errText(e, 'Could not reach the invoicing API')) } finally { setBusy(false) }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); void submit() }} aria-labelledby={`${id}-h`} className="stack" data-testid="inv-create-form">
      <h2 id={`${id}-h`}>Create an invoice</h2>
      <div className="hstack">
        <label htmlFor={`${id}-kind`}>Kind</label>
        <select id={`${id}-kind`} value={kind} onChange={(e) => setKind(e.target.value as 'receivable' | 'payable')} data-testid="inv-new-kind"><option value="receivable">Receivable (customer owes us)</option><option value="payable">Payable (we owe supplier)</option></select>
        <label htmlFor={`${id}-cp`}>Customer / supplier</label>
        <input id={`${id}-cp`} value={counterparty} maxLength={200} onChange={(e) => setCounterparty(e.target.value)} data-testid="inv-new-counterparty" />
        <label htmlFor={`${id}-cur`}>Currency</label>
        <input id={`${id}-cur`} value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} data-testid="inv-new-currency" />
      </div>
      <div className="hstack">
        <label htmlFor={`${id}-iss`}>Issue date</label><input id={`${id}-iss`} type="date" value={issue} onChange={(e) => setIssue(e.target.value)} />
        <label htmlFor={`${id}-due`}>Due date</label><input id={`${id}-due`} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        <label htmlFor={`${id}-notes`}>Notes</label><input id={`${id}-notes`} value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} />
      </div>
      <table className="stage-table">
        <caption className="sr-only">Invoice lines</caption>
        <thead><tr><th scope="col">Description</th><th scope="col">Quantity</th><th scope="col">Unit price</th><th scope="col">Tax rate</th><th scope="col">Remove</th></tr></thead>
        <tbody>{lines.map((l, i) => (
          <tr key={i} data-testid="inv-new-line">
            <td><input aria-label={`Line ${i + 1} description`} value={l.description} maxLength={500} onChange={(e) => set(i, { description: e.target.value })} data-testid="inv-line-desc" /></td>
            <td><input aria-label={`Line ${i + 1} quantity`} inputMode="numeric" value={l.quantity} onChange={(e) => set(i, { quantity: e.target.value })} data-testid="inv-line-qty" /></td>
            <td><input aria-label={`Line ${i + 1} unit price`} inputMode="decimal" value={l.unitPrice} onChange={(e) => set(i, { unitPrice: e.target.value })} data-testid="inv-line-price" /></td>
            <td><input aria-label={`Line ${i + 1} tax rate (optional)`} value={l.taxRate} maxLength={32} onChange={(e) => set(i, { taxRate: e.target.value })} data-testid="inv-line-tax" /></td>
            <td><button type="button" className="ghost small" disabled={lines.length <= 1} aria-label={`Remove line ${i + 1}`} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>Remove</button></td>
          </tr>
        ))}</tbody>
      </table>
      <div><button type="button" className="outline small" onClick={() => setLines((ls) => [...ls, blank()])} data-testid="inv-add-line">Add line</button></div>
      {error && <p role="alert" className="error-text" data-testid="inv-create-error">{error}</p>}
      {ok && <p role="status" data-testid="inv-create-ok">{ok}</p>}
      <button type="submit" disabled={busy} data-testid="inv-create">{busy ? 'Creating…' : 'Create draft invoice'}</button>
    </form>
  )
}

export function InvoicesPage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  const own = usePreviewSession(projectId, { disabled: !!session })
  const s = session ?? own
  return (
    <div data-testid="invoices-page" className="stack">
      <h1 id="invoices-h">Invoices</h1>
      <p className="muted">Receivable and payable invoices of the running project, with AR/AP aging. Amounts are exact minor units; a mistake is fixed by voiding, never by editing a posted invoice.</p>
      <PreviewSessionGate session={s} prefix="inv">
        <InvoicesPageBody key={projectId} projectId={projectId} session={s} />
      </PreviewSessionGate>
    </div>
  )
}
