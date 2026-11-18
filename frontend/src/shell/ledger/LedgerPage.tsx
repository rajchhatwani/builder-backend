import { Fragment, useCallback, useEffect, useId, useMemo, useState } from 'react'
import { sendRequest } from '../workbench/sendRequest'
import { PREVIEW_ORIGIN } from '../workbench/previewOrigin'
import {
  booksBalance, buildEntries, toBig, formatMinor, ledgerErrorMessage, newIdempotencyKey, parseLedgerJson, sumByCurrency,
  type Account, type AccountEntry, type Balances, type DraftLine, type Transaction,
} from './ledgerLogic'

const PAGE = 20
type Page<T> = { items: T[]; total: number }
type Load<T> = { s: 'idle' } | { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: T }

const isPage = (j: unknown): j is Page<unknown> => !!j && typeof j === 'object' && Array.isArray((j as { items?: unknown }).items)
const isBalances = (j: unknown): boolean => isPage(j) && Array.isArray((j as { totals?: unknown }).totals)
const UNEXPECTED = 'The ledger API answered with something unexpected. Check that this is the generated project API.'
const ACCOUNT_PAGE = 200
const HISTORY_PAGE = 50

const msg = (e: unknown, f: string) => (e instanceof Error ? e.message : f)

/** Ledger explorer for a generated project's money ledger (packs.money.ledger). Talks to the preview/runtime origin with a
 *  bearer token held in memory only (same mechanism as the Workbench request console). Read-mostly: posting and reversing
 *  are the only writes, nothing is ever edited or deleted. */
export function LedgerPage({ projectId, origin = PREVIEW_ORIGIN, doFetch = fetch }: { projectId: string; origin?: string | null; doFetch?: typeof fetch }) {
  const [token, setToken] = useState('')
  const [active, setActive] = useState('') // token in use; changes only on "Load ledger"
  const [accounts, setAccounts] = useState<Load<Account[]>>({ s: 'idle' })
  const [balances, setBalances] = useState<Load<Balances>>({ s: 'idle' })
  const [txs, setTxs] = useState<Load<Page<Transaction>>>({ s: 'idle' })
  const [page, setPage] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [hist, setHist] = useState<{ account: Account; load: Load<Page<AccountEntry>> } | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [revKey, setRevKey] = useState('')
  const [revError, setRevError] = useState<string | null>(null)
  const [revDone, setRevDone] = useState<string | null>(null)
  const tokenId = useId()

  const call = useCallback(async (method: string, path: string, body?: unknown) => {
    if (!origin) throw new Error('No preview API is configured')
    const r = await sendRequest({ url: origin + path, origin, method, body: body === undefined ? undefined : JSON.stringify(body), bearer: active || undefined }, doFetch)
    let json: unknown = null
    try { json = r.text ? parseLedgerJson(r.text) : null } catch { json = null }
    return { status: r.status, json }
  }, [origin, active, doFetch])

  const exponents = useMemo(() => {
    const m: Record<string, number> = {}
    if (accounts.s === 'ok') for (const a of accounts.v) m[a.currency] = a.exponent
    return m
  }, [accounts])

  useEffect(() => { setActive(''); setToken(''); setAccounts({ s: 'idle' }); setBalances({ s: 'idle' }); setTxs({ s: 'idle' }); setHist(null); setPage(0) }, [projectId])

  const get = useCallback(async <T,>(path: string, set: (l: Load<T>) => void, off: () => boolean, valid: (j: unknown) => boolean = isPage) => {
    set({ s: 'loading' })
    try {
      const r = await call('GET', path)
      if (off()) return
      const good = r.status >= 200 && r.status < 300
      set(good ? (valid(r.json) ? { s: 'ok', v: r.json as T } : { s: 'error', m: UNEXPECTED }) : { s: 'error', m: ledgerErrorMessage(r.status, r.json) })
    } catch (e) { if (!off()) set({ s: 'error', m: msg(e, 'Could not reach the ledger API') }) }
  }, [call])

  useEffect(() => {
    if (!active) return
    let dead = false
    const off = () => dead
    const off0 = off
    const setAcc = (l: Load<Account[]>) => setAccounts((prev) => (l.s === 'loading' && prev.s === 'ok' ? prev : l))
    void (async () => {
      setAcc({ s: 'loading' })
      try {
        const all: Account[] = []
        for (let off = 0; off < 100 * ACCOUNT_PAGE; off += ACCOUNT_PAGE) {
          const r = await call('GET', `/ledger/accounts?limit=${ACCOUNT_PAGE}&offset=${off}`)
          if (off0()) return
          if (r.status < 200 || r.status >= 300) { setAcc({ s: 'error', m: ledgerErrorMessage(r.status, r.json) }); return }
          if (!isPage(r.json)) { setAcc({ s: 'error', m: UNEXPECTED }); return }
          const items = r.json.items as Account[]
          all.push(...items)
          const total = typeof r.json.total === 'number' ? r.json.total : all.length
          if (items.length === 0 || all.length >= total) break
        }
        setAcc({ s: 'ok', v: all })
      } catch (e) { if (!off0()) setAcc({ s: 'error', m: msg(e, 'Could not reach the ledger API') }) }
    })()
    void get<Balances>('/ledger/balances', setBalances, off, isBalances)
    return () => { dead = true }
  }, [active, refresh, get, call])

  useEffect(() => {
    if (!active) return
    let dead = false
    void get<Page<Transaction>>(`/ledger/transactions?limit=${PAGE}&offset=${page * PAGE}`, setTxs, () => dead)
    return () => { dead = true }
  }, [active, page, refresh, get])

  const reload = () => { setPage(0); setRefresh((n) => n + 1); setHist(null) }

  async function showHistory(a: Account) {
    setHist({ account: a, load: { s: 'loading' } })
    let dead = false
    await get<Page<AccountEntry>>(`/ledger/accounts/${encodeURIComponent(a.id)}/entries?limit=${HISTORY_PAGE}`, (l) => { if (!dead) setHist((h) => (h && h.account.id === a.id ? { account: a, load: l } : h)) }, () => dead)
    dead = true
  }

  async function moreHistory() {
    const h = hist
    if (!h || h.load.s !== 'ok') return
    const have = h.load.v
    try {
      const r = await call('GET', `/ledger/accounts/${encodeURIComponent(h.account.id)}/entries?limit=${HISTORY_PAGE}&offset=${have.items.length}`)
      const good = r.status >= 200 && r.status < 300 && isPage(r.json)
      setHist((cur) => {
        if (!cur || cur.account.id !== h.account.id || cur.load.s !== 'ok') return cur
        if (!good) return { account: cur.account, load: { s: 'error', m: r.status >= 200 && r.status < 300 ? UNEXPECTED : ledgerErrorMessage(r.status, r.json) } }
        const more = r.json as Page<AccountEntry>
        return { account: cur.account, load: { s: 'ok', v: { items: [...cur.load.v.items, ...more.items], total: more.total ?? cur.load.v.total } } }
      })
    } catch (e) { setHist((cur) => (cur && cur.account.id === h.account.id ? { account: cur.account, load: { s: 'error', m: msg(e, 'Could not reach the ledger API') } } : cur)) }
  }

  async function reverse(t: Transaction) {
    setRevError(null)
    try {
      const r = await call('POST', `/ledger/transactions/${encodeURIComponent(t.id)}/reverse`, { idempotency_key: revKey })
      if (r.status === 200 || r.status === 201) { setConfirming(null); setRevDone(t.id); reload(); return }
      setRevError(ledgerErrorMessage(r.status, r.json, exponents))
    } catch (e) { setRevError(msg(e, 'Could not reach the ledger API')) }
  }

  const toggle = (id: string) => setOpen((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const acctOf = (id: string) => accounts.s === 'ok' ? accounts.v.find((a) => a.id === id) : undefined

  if (!origin) {
    return (
      <section aria-labelledby="ledger-h" data-testid="ledger-page">
        <h1 id="ledger-h">Ledger</h1>
        <p className="muted" data-testid="ledger-no-origin">No preview API is configured for this dashboard, so there is no ledger to read yet (set <code>VITE_PREVIEW_API_ORIGIN</code> to a running generated project with the money ledger on).</p>
      </section>
    )
  }

  return (
    <section aria-labelledby="ledger-h" data-testid="ledger-page" className="stack">
      <h1 id="ledger-h">Ledger</h1>
      <p className="muted">Double-entry books of the running project. Posted transactions are never edited or deleted; a mistake is fixed by reversing it. The token stays in this page only.</p>
      <form className="hstack" onSubmit={(e) => { e.preventDefault(); if (token) { setActive(token); setRefresh((n) => n + 1) } }} data-testid="ledger-token-form">
        <label htmlFor={tokenId}>Bearer token</label>
        <input id={tokenId} type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} data-testid="ledger-token" />
        <button type="submit" disabled={!token} data-testid="ledger-load">Load ledger</button>
        {active && <button type="button" className="outline" onClick={reload} data-testid="ledger-refresh">Refresh</button>}
      </form>
      {!active && <p className="muted" data-testid="ledger-notoken">Paste a bearer token for the project (a role allowed to read the ledger) to load it.</p>}

      {active && (
        <>
          <div data-testid="ledger-accounts-wrap">
            <h2>Accounts</h2>
            <State l={accounts} id="ledger-accounts" empty={(v) => v.length === 0} emptyText="No accounts yet. Create one with POST /ledger/accounts.">
              {(v) => (
                <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Accounts">
                  <table className="stage-table" data-testid="ledger-accounts">
                    <caption className="sr-only">Ledger accounts</caption>
                    <thead><tr><th scope="col">Code</th><th scope="col">Name</th><th scope="col">Kind</th><th scope="col">Currency</th><th scope="col">History</th></tr></thead>
                    <tbody>{v.map((a) => (
                      <tr key={a.id} data-testid="ledger-account-row">
                        <th scope="row">{a.code}</th><td>{a.name}</td><td>{a.kind}</td><td>{a.currency}</td>
                        <td><button type="button" className="ghost small" onClick={() => void showHistory(a)} aria-label={`Entry history of ${a.code}`} data-testid="ledger-history-btn">History</button></td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </State>
          </div>

          {hist && (
            <div data-testid="ledger-history">
              <h2>Entries of {hist.account.code} {hist.account.name}</h2>
              <State l={hist.load} id="ledger-history-state" empty={(v) => v.items.length === 0} emptyText="This account has no entries yet.">
                {(v) => (
                  <div className="stage-table-wrap" tabIndex={0} role="region" aria-label={`Entries of ${hist.account.code}`}>
                    <table className="stage-table">
                      <caption className="sr-only">Entry history of {hist.account.code}, newest first</caption>
                      <thead><tr><th scope="col">Posted</th><th scope="col">Description</th><th scope="col">Debit</th><th scope="col">Credit</th></tr></thead>
                      <tbody>{v.items.map((e) => (
                        <tr key={e.id} data-testid="ledger-history-row">
                          <td>{e.posted_at}</td><td>{e.description ?? ''}{e.reverses_id ? ' (reversal)' : ''}</td>
                          <Amounts side={e.direction} minor={e.amount_minor} exp={hist.account.exponent} />
                        </tr>
                      ))}</tbody>
                    </table>
                    {v.items.length < v.total && (
                      <p data-testid="ledger-history-more-wrap">
                        Showing {v.items.length} of {v.total} entries.{' '}
                        <button type="button" className="ghost small" data-testid="ledger-history-more" onClick={() => void moreHistory()}>Show more</button>
                      </p>
                    )}
                  </div>
                )}
              </State>
              <button type="button" className="ghost small" onClick={() => setHist(null)} data-testid="ledger-history-close">Close history</button>
            </div>
          )}

          <div data-testid="ledger-balances-wrap">
            <h2>Balances</h2>
            <State l={balances} id="ledger-balances-state" empty={(v) => v.items.length === 0} emptyText="No balances yet.">
              {(v) => (
                <>
                  <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Balances">
                    <table className="stage-table" data-testid="ledger-balances">
                      <caption className="sr-only">Balance per account; debits positive, credits negative</caption>
                      <thead><tr><th scope="col">Account</th><th scope="col">Currency</th><th scope="col">Debits</th><th scope="col">Credits</th><th scope="col">Balance</th></tr></thead>
                      <tbody>{v.items.map((b) => (
                        <tr key={b.account_id} data-testid="ledger-balance-row">
                          <th scope="row">{b.code} {b.name}</th><td>{b.currency}</td>
                          <td className="num">{formatMinor(b.debit_total_minor, b.exponent)}</td><td className="num">{formatMinor(b.credit_total_minor, b.exponent)}</td><td className="num">{formatMinor(b.balance_minor, b.exponent)}</td>
                        </tr>
                      ))}</tbody>
                      <tfoot>{v.totals.map((t) => {
                        const exp = exponents[t.currency] ?? v.items.find((b) => b.currency === t.currency)?.exponent ?? 2
                        return (
                          <tr key={t.currency} data-testid="ledger-total-row">
                            <th scope="row">Total {t.currency}</th><td>{t.currency}</td><td /><td />
                            <td className="num" data-testid="ledger-total-sum">{formatMinor(t.sum_minor, exp)}</td>
                          </tr>
                        )
                      })}</tfoot>
                    </table>
                  </div>
                  <p role="status" data-testid="ledger-balance-check" data-ok={booksBalance(v.totals) ? 'true' : 'false'} className={booksBalance(v.totals) ? '' : 'error-text'}>
                    {booksBalance(v.totals) ? 'Books balance: every currency sums to 0.' : 'Books do NOT balance: a currency total is not 0. Report this to the project owner.'}
                  </p>
                </>
              )}
            </State>
          </div>

          <div data-testid="ledger-transactions-wrap">
            <h2>Transactions</h2>
            {revDone && <p role="status" data-testid="ledger-reversed-ok">Transaction reversed; the reversal is the newest entry below.</p>}
            <State l={txs} id="ledger-transactions-state" empty={(v) => v.items.length === 0 && page === 0} emptyText="No transactions yet.">
              {(v) => (
                <>
                  <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Transactions">
                    <table className="stage-table" data-testid="ledger-transactions">
                      <caption className="sr-only">Transactions, newest first. Use Show entries to expand a row.</caption>
                      <thead><tr><th scope="col">Posted</th><th scope="col">Description</th><th scope="col">Reference</th><th scope="col">State</th><th scope="col">Actions</th></tr></thead>
                      <tbody>{v.items.map((t) => (
                        <Fragment key={t.id}>
                          <tr data-testid="ledger-tx-row">
                            <td>{t.posted_at}</td><td>{t.description ?? ''}</td><td>{t.reference ?? ''}</td>
                            <td>{t.reverses_id ? 'Reversal' : t.reversed_by_id ? 'Reversed' : 'Posted'}</td>
                            <td>
                              <button type="button" className="ghost small" aria-expanded={open.has(t.id)} aria-controls={`tx-${t.id}`} onClick={() => toggle(t.id)} data-testid="ledger-tx-toggle">{open.has(t.id) ? 'Hide entries' : 'Show entries'}</button>
                              {!t.reverses_id && !t.reversed_by_id && (
                                <button type="button" className="outline small" onClick={() => { setConfirming(t.id); setRevKey(newIdempotencyKey()); setRevError(null) }} data-testid="ledger-reverse-btn">Reverse</button>
                              )}
                            </td>
                          </tr>
                          {open.has(t.id) && (
                            <tr id={`tx-${t.id}`} data-testid="ledger-tx-entries">
                              <td colSpan={5}>
                                <table className="stage-table">
                                  <caption className="sr-only">Entries of this transaction</caption>
                                  <thead><tr><th scope="col">Line</th><th scope="col">Account</th><th scope="col">Currency</th><th scope="col">Debit</th><th scope="col">Credit</th></tr></thead>
                                  <tbody>{t.entries.map((en) => {
                                    const a = acctOf(en.account_id)
                                    return (
                                      <tr key={en.id} data-testid="ledger-entry-row">
                                        <td>{en.line_no}</td><td>{a ? `${a.code} ${a.name}` : en.account_id}</td><td>{en.currency}</td>
                                        <Amounts side={en.direction} minor={en.amount_minor} exp={a?.exponent ?? exponents[en.currency] ?? 2} />
                                      </tr>
                                    )
                                  })}</tbody>
                                </table>
                              </td>
                            </tr>
                          )}
                          {confirming === t.id && (
                            <tr data-testid="ledger-reverse-confirm">
                              <td colSpan={5}>
                                <div role="alertdialog" aria-label="Confirm reversal" className="hstack">
                                  <span>Reverse this transaction? A new transaction negating every entry will be posted. This cannot be undone.</span>
                                  <button type="button" onClick={() => void reverse(t)} data-testid="ledger-reverse-yes">Yes, reverse</button>
                                  <button type="button" className="outline" onClick={() => setConfirming(null)} data-testid="ledger-reverse-no">Cancel</button>
                                </div>
                                {revError && <p role="alert" className="error-text" data-testid="ledger-reverse-error">{revError}</p>}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}</tbody>
                    </table>
                  </div>
                  <div className="hstack">
                    <button type="button" className="btn btn-sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)} data-testid="ledger-prev">Previous</button>
                    <span className="small-text" data-testid="ledger-page-label">Page {page + 1} of {Math.max(1, Math.ceil(v.total / PAGE))}</span>
                    <button type="button" className="btn btn-sm" disabled={(page + 1) * PAGE >= v.total} onClick={() => setPage((p) => p + 1)} data-testid="ledger-next">Next</button>
                  </div>
                </>
              )}
            </State>
          </div>

          {accounts.s === 'ok' && accounts.v.length > 0 && <PostForm accounts={accounts.v} exponents={exponents} call={call} onPosted={reload} />}
        </>
      )}
    </section>
  )
}

function Amounts({ side, minor, exp }: { side: string; minor: import('./ledgerLogic').Minor; exp: number }) {
  const debit = side === 'debit'
  const text = formatMinor(debit ? minor : -toBig(minor), exp)
  return <><td className="num" data-testid="ledger-debit">{debit ? text : ''}</td><td className="num" data-testid="ledger-credit">{debit ? '' : text}</td></>
}

function State<T>({ l, id, empty, emptyText, children }: { l: Load<T>; id: string; empty: (v: T) => boolean; emptyText: string; children: (v: T) => React.ReactNode }) {
  if (l.s === 'idle') return null
  if (l.s === 'loading') return <p role="status" className="muted" data-testid={`${id}-loading`}>Loading…</p>
  if (l.s === 'error') return <p role="alert" className="error-text" data-testid={`${id}-error`}>{l.m}</p>
  if (empty(l.v)) return <p className="muted" data-testid={`${id}-empty`}>{emptyText}</p>
  return <>{children(l.v)}</>
}

function PostForm({ accounts, exponents, call, onPosted }: { accounts: Account[]; exponents: Record<string, number>; call: (m: string, p: string, b?: unknown) => Promise<{ status: number; json: unknown }>; onPosted: () => void }) {
  const blank = (): DraftLine => ({ accountId: '', side: 'debit', amount: '' })
  const [lines, setLines] = useState<DraftLine[]>([blank(), { ...blank(), side: 'credit' }])
  const [key, setKey] = useState(newIdempotencyKey)
  const [description, setDescription] = useState('')
  const [reference, setReference] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const id = useId()

  const built = buildEntries(lines, accounts)
  const sums = built.entries
    ? sumByCurrency(built.entries.map((e) => ({ currency: accounts.find((a) => a.id === e.account_id)!.currency, amount_minor: e.amount_minor })))
    : null
  const set = (i: number, p: Partial<DraftLine>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...p } : l)))

  async function submit() {
    setError(null); setOk(null)
    if (!built.entries) { setError(built.error); return }
    setBusy(true)
    try {
      const body: Record<string, unknown> = { idempotency_key: key, entries: built.entries }
      if (description) body.description = description
      if (reference) body.reference = reference
      const r = await call('POST', '/ledger/transactions', body)
      if (r.status === 200 || r.status === 201) {
        setOk(r.status === 200 ? 'This key was already posted; showing the original transaction (no duplicate was created).' : 'Transaction posted.')
        setKey(newIdempotencyKey()); setLines([blank(), { ...blank(), side: 'credit' }]); setDescription(''); setReference('')
        onPosted()
      } else setError(ledgerErrorMessage(r.status, r.json, exponents))
    } catch (e) { setError(msg(e, 'Could not reach the ledger API')) } finally { setBusy(false) }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); void submit() }} data-testid="ledger-post-form" aria-labelledby={`${id}-h`} className="stack">
      <h2 id={`${id}-h`}>Post a transaction</h2>
      <div className="hstack">
        <label htmlFor={`${id}-key`}>Idempotency key</label>
        <input id={`${id}-key`} value={key} onChange={(e) => setKey(e.target.value)} maxLength={128} data-testid="ledger-key" />
        <button type="button" className="outline small" onClick={() => setKey(newIdempotencyKey())}>New key</button>
      </div>
      <div className="hstack">
        <label htmlFor={`${id}-desc`}>Description</label>
        <input id={`${id}-desc`} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} data-testid="ledger-description" />
        <label htmlFor={`${id}-ref`}>Reference</label>
        <input id={`${id}-ref`} value={reference} onChange={(e) => setReference(e.target.value)} maxLength={128} data-testid="ledger-reference" />
      </div>
      <table className="stage-table">
        <caption className="sr-only">Entries of the new transaction</caption>
        <thead><tr><th scope="col">Account</th><th scope="col">Side</th><th scope="col">Amount</th><th scope="col">Remove</th></tr></thead>
        <tbody>{lines.map((l, i) => (
          <tr key={i} data-testid="ledger-line">
            <td><select aria-label={`Entry ${i + 1} account`} value={l.accountId} onChange={(e) => set(i, { accountId: e.target.value })} data-testid="ledger-line-account">
              <option value="">Choose…</option>{accounts.map((a) => <option key={a.id} value={a.id}>{a.code} {a.name} ({a.currency})</option>)}
            </select></td>
            <td><select aria-label={`Entry ${i + 1} side`} value={l.side} onChange={(e) => set(i, { side: e.target.value as 'debit' | 'credit' })} data-testid="ledger-line-side">
              <option value="debit">Debit</option><option value="credit">Credit</option>
            </select></td>
            <td><input aria-label={`Entry ${i + 1} amount`} inputMode="decimal" value={l.amount} onChange={(e) => set(i, { amount: e.target.value })} data-testid="ledger-line-amount" /></td>
            <td><button type="button" className="ghost small" disabled={lines.length <= 2} aria-label={`Remove entry ${i + 1}`} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>Remove</button></td>
          </tr>
        ))}</tbody>
      </table>
      <div className="hstack">
        <button type="button" className="outline small" onClick={() => setLines((ls) => [...ls, blank()])} disabled={lines.length >= 100} data-testid="ledger-add-line">Add entry</button>
        <span className="small-text" data-testid="ledger-draft-sum" aria-live="polite">
          {sums ? [...sums].map(([cur, s]) => `${cur}: ${s === 0n ? 'balanced' : `off by ${formatMinor(s, exponents[cur] ?? 2)}`}`).join(' | ') : 'Fill in every entry to check the balance.'}
        </span>
      </div>
      {error && <p role="alert" className="error-text" data-testid="ledger-post-error">{error}</p>}
      {ok && <p role="status" data-testid="ledger-post-ok">{ok}</p>}
      <button type="submit" disabled={busy} data-testid="ledger-post">{busy ? 'Posting…' : 'Post transaction'}</button>
    </form>
  )
}
