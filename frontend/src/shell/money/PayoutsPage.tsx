import { useEffect, useId, useState } from 'react'
import { PreviewSessionGate } from '../preview/PreviewSessionGate'
import { usePreviewSession } from '../preview/usePreviewSession'
import type { PreviewSession } from '../preview/previewSession'
import { defaultExponent, formatMinor, moneyErrorMessage, newIdempotencyKey, validSeller, type Invoice, type Minor } from './moneyLogic'
import { State, UNEXPECTED, errText, isPage, ok2xx, useCall, type Load, type Page } from './moneyShared'

interface Payout { id: string; invoice_id: string; seller: string; currency: string; gross_minor: Minor; commission_bp: number; commission_minor: Minor; seller_minor: Minor; created_at: string }
interface PayoutTotal { seller: string; currency: string; count: number; gross_minor: Minor; commission_minor: Minor; seller_minor: Minor }
const NO_BLOCK = 'This project has no payouts block (the payouts API answered 404). Enable payouts in the money.invoicing pack of the spec to use this page.'

function PayoutsPageBody({ session }: { projectId: string; session: PreviewSession }) {
  const call = useCall(session)
  const [list, setList] = useState<Load<Page<Payout>>>({ s: 'idle' })
  const [totals, setTotals] = useState<Load<PayoutTotal[]>>({ s: 'idle' })
  const [paid, setPaid] = useState<Load<Invoice[]>>({ s: 'idle' })
  const [refresh, setRefresh] = useState(0)
  const [disabled, setDisabled] = useState(false)
  const id = useId()
  const [invoiceId, setInvoiceId] = useState('')
  const [seller, setSeller] = useState('')
  const [key, setKey] = useState(newIdempotencyKey)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  useEffect(() => {
    let dead = false
    setList({ s: 'loading' }); setTotals({ s: 'loading' }); setPaid({ s: 'loading' })
    void (async () => {
      try {
        const [a, t, p] = await Promise.all([call('GET', '/payouts?limit=100&offset=0'), call('GET', '/payouts/totals'), call('GET', '/invoices?kind=receivable&status=paid&limit=200&offset=0')])
        if (dead) return
        if (a.status === 404 && !(a.json as { code?: string } | null)?.code) { setDisabled(true); return }
        setDisabled(false)
        setList(ok2xx(a.status) ? (isPage(a.json) ? { s: 'ok', v: a.json as Page<Payout> } : { s: 'error', m: UNEXPECTED }) : { s: 'error', m: moneyErrorMessage(a.status, a.json, 'payouts') })
        setTotals(ok2xx(t.status) ? (Array.isArray(t.json) ? { s: 'ok', v: t.json as PayoutTotal[] } : { s: 'error', m: UNEXPECTED }) : { s: 'error', m: moneyErrorMessage(t.status, t.json, 'payouts') })
        setPaid(ok2xx(p.status) ? (isPage(p.json) ? { s: 'ok', v: p.json.items as Invoice[] } : { s: 'error', m: UNEXPECTED }) : { s: 'error', m: moneyErrorMessage(p.status, p.json) })
      } catch (e) {
        if (dead) return
        const m = errText(e, 'Could not reach the payouts API')
        setList({ s: 'error', m }); setTotals({ s: 'error', m }); setPaid({ s: 'error', m })
      }
    })()
    return () => { dead = true }
  }, [call, refresh])

  if (disabled) return <p role="status" className="muted" data-testid="payouts-disabled">{NO_BLOCK}</p>

  const paidOut = new Set(list.s === 'ok' ? list.v.items.map((p) => p.invoice_id) : [])
  const candidates = paid.s === 'ok' ? paid.v.filter((i) => !paidOut.has(i.id)) : []
  const chosen = candidates.find((i) => i.id === invoiceId)

  async function run() {
    setError(null); setDone(null)
    if (!chosen) { setError('Choose a fully paid invoice.'); setConfirm(false); return }
    if (!validSeller(seller)) { setError('Seller must be 1-64 characters: letters, digits and . _ : @ - only, starting with a letter or digit, no spaces.'); setConfirm(false); return }
    setBusy(true)
    try {
      const r = await call('POST', '/payouts/run', { idempotency_key: key, invoice_id: chosen.id, seller })
      if (ok2xx(r.status)) {
        setDone(r.status === 200 ? 'This key was already used; showing the original payout (no duplicate was created).' : 'Payout run.')
        setConfirm(false); setInvoiceId(''); setSeller(''); setKey(newIdempotencyKey()); setRefresh((n) => n + 1)
      } else { setError(moneyErrorMessage(r.status, r.json, 'payouts')); setConfirm(false) }
    } catch (e) { setError(errText(e, 'Could not reach the payouts API')); setConfirm(false) } finally { setBusy(false) }
  }

  return (
    <>
      <div><button type="button" className="outline" onClick={() => setRefresh((n) => n + 1)} data-testid="payouts-refresh">Refresh</button></div>

      <form className="stack" aria-labelledby={`${id}-h`} data-testid="payout-form" onSubmit={(e) => { e.preventDefault(); setError(null); setDone(null); if (chosen && validSeller(seller)) setConfirm(true); else void run() }}>
        <h2 id={`${id}-h`}>Run a payout</h2>
        <State l={paid} id="payout-invoices" empty={() => false} emptyText="">
          {() => candidates.length === 0 ? <p className="muted" data-testid="payout-no-candidates">No fully paid receivable invoice is waiting for a payout.</p> : (
            <div className="hstack">
              <label htmlFor={`${id}-inv`}>Paid invoice</label>
              <select id={`${id}-inv`} value={invoiceId} onChange={(e) => { setInvoiceId(e.target.value); setConfirm(false) }} data-testid="payout-invoice">
                <option value="">Choose…</option>
                {candidates.map((i) => <option key={i.id} value={i.id}>{i.number ?? i.id} {i.counterparty} ({i.currency} {formatMinor(i.total_minor, i.exponent)})</option>)}
              </select>
              <label htmlFor={`${id}-sel`}>Seller</label>
              <input id={`${id}-sel`} value={seller} maxLength={64} onChange={(e) => { setSeller(e.target.value); setConfirm(false) }} data-testid="payout-seller" />
              <label htmlFor={`${id}-key`}>Idempotency key</label>
              <input id={`${id}-key`} value={key} maxLength={128} onChange={(e) => setKey(e.target.value)} data-testid="payout-key" />
              <button type="submit" disabled={busy} data-testid="payout-run">Run payout</button>
            </div>
          )}
        </State>
        {confirm && chosen && (
          <div role="alertdialog" aria-label="Confirm payout" className="hstack" data-testid="payout-confirm">
            <span>Pay out {chosen.currency} {formatMinor(chosen.total_minor, chosen.exponent)} for {chosen.number ?? chosen.id} to seller {seller}? A payout is irreversible and the seller label is not checked against the invoice customer.</span>
            <button type="button" disabled={busy} onClick={() => void run()} data-testid="payout-yes">{busy ? 'Running…' : 'Yes, run payout'}</button>
            <button type="button" className="outline" onClick={() => setConfirm(false)}>Cancel</button>
          </div>
        )}
        {error && <p role="alert" className="error-text" data-testid="payout-error">{error}</p>}
        {done && <p role="status" data-testid="payout-ok">{done}</p>}
      </form>

      <div>
        <h2>Totals</h2>
        <State l={totals} id="payout-totals" empty={(v) => v.length === 0} emptyText="No payouts yet.">
          {(v) => (
            <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Payout totals">
              <table className="stage-table" data-testid="payout-totals">
                <caption className="sr-only">Payout totals per seller and currency</caption>
                <thead><tr><th scope="col">Seller</th><th scope="col">Currency</th><th scope="col">Payouts</th><th scope="col">Gross</th><th scope="col">Commission</th><th scope="col">Seller receives</th></tr></thead>
                <tbody>{v.map((t) => { const e = defaultExponent(t.currency); return (
                  <tr key={`${t.seller}|${t.currency}`} data-testid="payout-total-row">
                    <th scope="row">{t.seller}</th><td>{t.currency}</td><td className="num">{t.count}</td>
                    <td className="num">{formatMinor(t.gross_minor, e)}</td><td className="num">{formatMinor(t.commission_minor, e)}</td><td className="num" data-testid="payout-total-seller">{formatMinor(t.seller_minor, e)}</td>
                  </tr>) })}</tbody>
              </table>
            </div>
          )}
        </State>
      </div>

      <div>
        <h2>Payouts</h2>
        <State l={list} id="payout-list" empty={(v) => v.items.length === 0} emptyText="No payouts yet.">
          {(v) => (
            <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Payouts">
              <table className="stage-table" data-testid="payout-table">
                <caption className="sr-only">Payouts, newest first</caption>
                <thead><tr><th scope="col">Date</th><th scope="col">Seller</th><th scope="col">Invoice</th><th scope="col">Currency</th><th scope="col">Gross</th><th scope="col">Commission</th><th scope="col">Seller receives</th></tr></thead>
                <tbody>{v.items.map((p) => { const e = defaultExponent(p.currency); return (
                  <tr key={p.id} data-testid="payout-row">
                    <td>{p.created_at}</td><th scope="row">{p.seller}</th><td>{p.invoice_id}</td><td>{p.currency}</td>
                    <td className="num">{formatMinor(p.gross_minor, e)}</td><td className="num">{formatMinor(p.commission_minor, e)} ({p.commission_bp / 100}%)</td><td className="num">{formatMinor(p.seller_minor, e)}</td>
                  </tr>) })}</tbody>
              </table>
            </div>
          )}
        </State>
      </div>
    </>
  )
}

export function PayoutsPage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  const own = usePreviewSession(projectId, { disabled: !!session })
  const s = session ?? own
  return (
    <div data-testid="payouts-page" className="stack">
      <h1 id="payouts-h">Payouts</h1>
      <p className="muted">Pay sellers out of fully paid invoices. A payout is irreversible.</p>
      <PreviewSessionGate session={s} prefix="payouts">
        <PayoutsPageBody key={projectId} projectId={projectId} session={s} />
      </PreviewSessionGate>
    </div>
  )
}
