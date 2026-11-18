import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { sendRequest } from '../workbench/sendRequest'
import { PREVIEW_ORIGIN } from '../workbench/previewOrigin'
import { newIdempotencyKey } from '../ledger/ledgerLogic'
import {
  addDays, bookingErrorMessage, buildGrid, cancellationNote, findOverlaps, formatDay, formatInstant, isActive, localParts, moveFocus, parseBookingJson, parseLocalInput,
  weekInstants, weekRange, type Booking, type Cell, type CellState, type Resource, type Slot,
} from './calendarLogic'

type Page<T> = { items: T[]; total?: number }
type Avail = { slots: Slot[] }
type Load<T> = { s: 'idle' } | { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: T }
const msg = (e: unknown, f: string) => (e instanceof Error ? e.message : f)

const COLOR: Record<CellState, { bg: string; fg: string; border: string }> = {
  free: { bg: '#dafbe1', fg: '#0f3d1c', border: '#1a7f37' },
  held: { bg: '#fff8c5', fg: '#4d3800', border: '#9a6700' },
  booked: { bg: '#ddf4ff', fg: '#05326b', border: '#0969da' },
  cancelled: { bg: '#eaeef2', fg: '#3b434b', border: '#6e7781' },
}

/** Booking calendar for a generated project's booking pack (D12). Week grid in the resource's time zone, hold -> confirm -> cancel.
 *  Bearer token held in memory only (same mechanism as the Ledger explorer). The server is the only authority on availability. */
export function BookingsPage({ projectId, origin = PREVIEW_ORIGIN, doFetch = fetch, now = Date.now }: { projectId: string; origin?: string | null; doFetch?: typeof fetch; now?: () => number }) {
  const [token, setToken] = useState('')
  const [active, setActive] = useState('')
  const [resources, setResources] = useState<Load<Page<Resource>>>({ s: 'idle' })
  const [resourceId, setResourceId] = useState('')
  const [anchor, setAnchor] = useState('')
  const [avail, setAvail] = useState<Load<Avail>>({ s: 'idle' })
  const [bookings, setBookings] = useState<Load<Page<Booking>>>({ s: 'idle' })
  const [refresh, setRefresh] = useState(0)
  const [selKey, setSelKey] = useState<string | null>(null)
  const [focus, setFocus] = useState<[number, number]>([0, 0])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirmCancel, setConfirmCancel] = useState<string | null>(null) // id of the booking whose cancel is being confirmed
  const [idem, setIdem] = useState(() => newIdempotencyKey())
  const [customer, setCustomer] = useState('')
  const [notes, setNotes] = useState('')
  const [reason, setReason] = useState('')
  const tokenId = useId(), resId = useId(), custId = useId(), notesId = useId(), reasonId = useId()
  const loaded = useRef('')
  const cellRefs = useRef(new Map<string, HTMLButtonElement>())

  const resource = resources.s === 'ok' ? resources.v.items.find((r) => r.id === resourceId) ?? null : null
  const tz = resource?.timezone ?? 'UTC'

  const call = useCallback(async (method: string, path: string, body?: unknown) => {
    if (!origin) throw new Error('No preview API is configured')
    const r = await sendRequest({ url: origin + path, origin, method, body: body === undefined ? undefined : JSON.stringify(body), bearer: active || undefined }, doFetch)
    let json: unknown = null
    try { json = r.text ? parseBookingJson(r.text) : null } catch { json = null }
    return { status: r.status, json }
  }, [origin, active, doFetch])

  useEffect(() => { loaded.current = ''; setActive(''); setToken(''); setResources({ s: 'idle' }); setResourceId(''); setAnchor(''); setAvail({ s: 'idle' }); setBookings({ s: 'idle' }); setSelKey(null); setError(null); setNotice(null) }, [projectId])

  const get = useCallback(async <T,>(path: string, set: (l: Load<T>) => void, off: () => boolean, keep = false) => {
    if (!keep) set({ s: 'loading' })
    try {
      const r = await call('GET', path)
      if (off()) return
      set(r.status >= 200 && r.status < 300 ? { s: 'ok', v: r.json as T } : { s: 'error', m: bookingErrorMessage(r.status, r.json) })
    } catch (e) { if (!off()) set({ s: 'error', m: msg(e, 'Could not reach the booking API') }) }
  }, [call])

  useEffect(() => {
    if (!active) return
    let dead = false
    void get<Page<Resource>>('/booking/resources?limit=200&active=true', (l) => {
      setResources(l)
      if (l.s === 'ok') setResourceId((cur) => (l.v.items.some((r) => r.id === cur) ? cur : l.v.items[0]?.id ?? ''))
    }, () => dead)
    return () => { dead = true }
  }, [active, get])

  // pick the week that contains "today" in the resource zone once a resource is known
  useEffect(() => { if (resource && !anchor) setAnchor(localParts(now(), resource.timezone).date) }, [resource, anchor, now])

  const week = useMemo(() => (anchor ? weekRange(anchor) : null), [anchor])

  useEffect(() => {
    if (!active || !resource || !week) return
    let dead = false
    const off = () => dead
    const { from, to } = weekInstants(week, resource.timezone)
    // same resource and week as the last load: refresh in place so the grid (focus, selection) stays mounted
    const loadKey = `${resource.id}|${week.from}`
    const keep = loaded.current === loadKey
    loaded.current = loadKey
    void get<Page<Booking>>(`/booking/bookings?resource_id=${encodeURIComponent(resource.id)}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=200`, setBookings, off, keep)
    if (resource.mode === 'slot') void get<Avail>(`/booking/resources/${encodeURIComponent(resource.id)}/availability?from=${week.from}&to=${week.to}&include_taken=true`, setAvail, off, keep)
    else setAvail({ s: 'ok', v: { slots: [] } })
    return () => { dead = true }
  }, [active, resource, week, refresh, get])

  const nowMs = now()
  const grid = useMemo(() => {
    if (!week || bookings.s !== 'ok' || avail.s !== 'ok') return null
    return buildGrid(week.days, avail.v.slots, bookings.v.items, tz, nowMs)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [week, bookings, avail, tz])
  const exists = useMemo(() => (grid ? grid.cells.map((row) => row.map((c) => c !== null)) : []), [grid])
  // roving tabindex needs exactly one tab stop: fall back to the first existing cell when the remembered one is empty
  const tabStop = useMemo<[number, number]>(() => {
    if (exists[focus[0]]?.[focus[1]]) return focus
    for (let r = 0; r < exists.length; r++) for (let c = 0; c < exists[r].length; c++) if (exists[r][c]) return [r, c]
    return focus
  }, [exists, focus])
  const overlapsFound = useMemo(() => (bookings.s === 'ok' ? findOverlaps(bookings.v.items, nowMs) : []), [bookings]) // eslint-disable-line react-hooks/exhaustive-deps
  const selected: Cell | null = grid && selKey ? grid.cells.flat().find((c) => c?.key === selKey) ?? null : null
  // every booking in the cell, active ones first (a pool/range cell can hold several); a dead one only when nothing is active
  const shown = useMemo<Booking[]>(() => {
    if (!selected) return []
    const act = selected.bookings.filter((b) => isActive(b, nowMs))
    return act.length ? act : selected.booking ? [selected.booking] : []
  }, [selected, nowMs])
  const reload = () => setRefresh((n) => n + 1)

  function choose(c: Cell) {
    setSelKey(c.key); setError(null); setNotice(null); setConfirmCancel(null); setCustomer(''); setNotes(''); setReason(''); setIdem(newIdempotencyKey())
  }
  function onKey(e: React.KeyboardEvent, r: number, c: number) {
    if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
    e.preventDefault()
    const [nr, nc] = moveFocus(exists, r, c, e.key)
    setFocus([nr, nc])
    cellRefs.current.get(`${nr}:${nc}`)?.focus()
  }

  async function act(run: () => Promise<{ status: number; json: unknown }>, ok: (b: Booking) => string) {
    setBusy(true); setError(null); setNotice(null)
    try {
      const r = await run()
      if (r.status >= 200 && r.status < 300) { setNotice(ok(r.json as Booking)); setConfirmCancel(null); setCustomer(''); setNotes(''); setReason(''); setIdem(newIdempotencyKey()); reload() }
      else { setError(bookingErrorMessage(r.status, r.json)); reload() } // state may have changed (slot taken, hold expired): show the truth
    } catch (e) { setError(msg(e, 'Could not reach the booking API')) } finally { setBusy(false) }
  }
  const holdBody = (startsAt: string, endsAt: string, extra: Record<string, unknown> = {}) => ({
    resource_id: resourceId, starts_at: startsAt, ends_at: endsAt, confirm: false, idempotency_key: idem,
    ...(customer.trim() ? { customer_ref: customer.trim() } : {}), ...(notes.trim() ? { notes: notes.trim() } : {}), ...extra,
  })
  const hold = (startsAt: string, endsAt: string, extra?: Record<string, unknown>) =>
    act(() => call('POST', '/booking/bookings', holdBody(startsAt, endsAt, extra)), (b) => `Hold created for ${formatInstant(b.starts_at, tz)}${b.hold_expires_at ? `; confirm before ${formatInstant(b.hold_expires_at, tz)}` : ''}.`)
  const confirm = (b: Booking) => act(() => call('POST', `/booking/bookings/${encodeURIComponent(b.id)}/confirm`), (x) => `Booking confirmed for ${formatInstant(x.starts_at, tz)}.`)
  const cancel = (b: Booking) => act(() => call('POST', `/booking/bookings/${encodeURIComponent(b.id)}/cancel`, reason.trim() ? { reason: reason.trim() } : {}), (x) => cancellationNote(x))

  if (!origin) {
    return (
      <section aria-labelledby="bk-h" data-testid="bookings-page">
        <h1 id="bk-h">Bookings</h1>
        <p className="muted" data-testid="bookings-no-origin">No preview API is configured for this dashboard, so there is no calendar to read yet (set <code>VITE_PREVIEW_API_ORIGIN</code> to a running generated project with the booking pack on).</p>
      </section>
    )
  }

  return (
    <section aria-labelledby="bk-h" data-testid="bookings-page" className="stack">
      <h1 id="bk-h">Bookings</h1>
      <p className="muted">Week calendar of the running project&apos;s bookable resources. Create a hold, confirm it before it expires, or cancel. The token stays in this page only.</p>
      <form className="hstack" onSubmit={(e) => { e.preventDefault(); if (token) { loaded.current = ''; setActive(token); setRefresh((n) => n + 1) } }} data-testid="bookings-token-form">
        <label htmlFor={tokenId}>Bearer token</label>
        <input id={tokenId} type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} data-testid="bookings-token" />
        <button type="submit" disabled={!token} data-testid="bookings-load">Load calendar</button>
      </form>
      {!active && <p className="muted" data-testid="bookings-notoken">Paste a bearer token for the project (a role allowed to read or make bookings) to load it.</p>}

      {active && resources.s === 'loading' && <p role="status" className="muted" data-testid="bookings-resources-loading">Loading resources…</p>}
      {active && resources.s === 'error' && <p role="alert" className="error-text" data-testid="bookings-resources-error">{resources.m}</p>}
      {active && resources.s === 'ok' && (resources.v.total ?? 0) > resources.v.items.length && <p role="alert" className="error-text" data-testid="bookings-resources-truncated">Only the first {resources.v.items.length} of {resources.v.total} resources are listed.</p>}
      {active && resources.s === 'ok' && resources.v.items.length === 0 && <p className="muted" data-testid="bookings-resources-empty">No bookable resources yet. Create one with POST /booking/resources.</p>}

      {active && resources.s === 'ok' && resource && week && (
        <>
          <div className="hstack" role="group" aria-label="Calendar controls" data-testid="bookings-controls">
            <label htmlFor={resId}>Resource</label>
            <select id={resId} value={resourceId} onChange={(e) => { setResourceId(e.target.value); setAnchor(''); setSelKey(null); setError(null); setNotice(null) }} data-testid="bookings-resource">
              {resources.v.items.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.kind}, {r.mode})</option>)}
            </select>
            <button type="button" className="outline small" onClick={() => setAnchor(addDays(week.from, -7))} data-testid="bookings-prev">Previous week</button>
            <span data-testid="bookings-week-label" aria-live="polite">{formatDay(week.from)} to {formatDay(week.to)}</span>
            <button type="button" className="outline small" onClick={() => setAnchor(addDays(week.from, 7))} data-testid="bookings-next">Next week</button>
            <button type="button" className="ghost small" onClick={() => setAnchor(localParts(now(), tz).date)} data-testid="bookings-today">This week</button>
            <button type="button" className="ghost small" onClick={reload} data-testid="bookings-refresh">Refresh</button>
          </div>
          <p className="small-text muted" data-testid="bookings-tz">Times are shown in the resource&apos;s time zone: {resource.timezone}.</p>

          {(avail.s === 'loading' || bookings.s === 'loading') && <p role="status" className="muted" data-testid="bookings-loading">Loading the week…</p>}
          {avail.s === 'error' && <p role="alert" className="error-text" data-testid="bookings-grid-error">{avail.m}</p>}
          {bookings.s === 'error' && <p role="alert" className="error-text" data-testid="bookings-grid-error-bookings">{bookings.m}</p>}
          {bookings.s === 'ok' && (bookings.v.total ?? 0) > bookings.v.items.length && <p role="alert" className="error-text" data-testid="bookings-truncated">Only the first {bookings.v.items.length} of {bookings.v.total} bookings this week are shown, so some slots may look free that are not.</p>}
          {overlapsFound.length > 0 && <p role="alert" className="error-text" data-testid="bookings-overlap-warning">{overlapsFound.length} overlapping active booking pair(s) are shown below. The server should refuse these, please report it.</p>}

          {grid && grid.times.length === 0 && <p className="muted" data-testid="bookings-grid-empty">Nothing bookable or booked this week. Try another week{resource.mode === 'slot' ? ' (slots come from the resource schedule)' : ''}.</p>}

          {grid && grid.times.length > 0 && (
            <div className="stage-table-wrap" role="region" aria-label="Week calendar" tabIndex={-1}>
              <table role="grid" className="stage-table" data-testid="bookings-grid" aria-label={`Week of ${formatDay(week.from)} for ${resource.name}`}>
                <thead>
                  <tr><th scope="col"><span className="sr-only">Time</span></th>{grid.days.map((d) => <th key={d} scope="col" data-testid="bookings-day">{formatDay(d)}</th>)}</tr>
                </thead>
                <tbody>
                  {grid.times.map((t, r) => (
                    <tr key={t} data-testid="bookings-row">
                      <th scope="row">{t}</th>
                      {grid.cells[r].map((c, ci) => (
                        <td key={ci} role="gridcell" style={{ padding: 2 }}>
                          {c && (
                            <button
                              type="button"
                              ref={(el) => { if (el) cellRefs.current.set(`${r}:${ci}`, el); else cellRefs.current.delete(`${r}:${ci}`) }}
                              tabIndex={tabStop[0] === r && tabStop[1] === ci ? 0 : -1}
                              aria-label={`${formatDay(c.day)} ${c.time}, ${c.label}`}
                              aria-pressed={selKey === c.key}
                              data-testid="bookings-cell"
                              data-state={c.state}
                              data-key={c.key}
                              data-pos={`${r}:${ci}`}
                              onFocus={() => setFocus([r, ci])}
                              onClick={() => choose(c)}
                              onKeyDown={(e) => onKey(e, r, ci)}
                              style={{ width: '100%', minWidth: 64, padding: '4px 2px', fontSize: 12, cursor: 'pointer', background: COLOR[c.state].bg, color: COLOR[c.state].fg, border: `${selKey === c.key ? 3 : 1}px ${c.label === 'Expired' ? 'dashed' : 'solid'} ${COLOR[c.state].border}` }}
                            >{c.label}</button>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="small-text muted" data-testid="bookings-legend">Green = free, yellow = held (not yet confirmed), blue = booked or taken, grey = cancelled or expired. Use the arrow keys to move between cells, Enter to select.</p>

          <div role="region" aria-label="Booking details" data-testid="bookings-details" className="stack">
            {notice && <p role="status" data-testid="bookings-notice">{notice}</p>}
            {error && <p role="alert" className="error-text" data-testid="bookings-error">{error}</p>}
            {resource.mode !== 'slot' && <RangeForm key={resource.id} resource={resource} call={call} busy={busy} onHold={hold} tz={tz} />}
            {!selected && resource.mode === 'slot' && !notice && !error && <p className="muted" data-testid="bookings-select-hint">Select a cell to hold, confirm or cancel a slot.</p>}
            {selected && (
              <div data-testid="bookings-selected" data-state={selected.state} className="stack">
                <h2>{formatDay(selected.day)} {selected.time} ({selected.label})</h2>
                {shown.map((bk) => (
                  <div key={bk.id} className="stack" data-testid="bookings-booking">
                    <p className="small-text" data-testid="bookings-booking-info">
                      Booking {bk.status}{bk.customer_ref ? ` for ${bk.customer_ref}` : ''}, {formatInstant(bk.starts_at, tz)} to {formatInstant(bk.ends_at, tz)}
                      {bk.status === 'held' && bk.hold_expires_at ? `; hold expires ${formatInstant(bk.hold_expires_at, tz)}` : ''}
                      {bk.status === 'cancelled' ? `. ${cancellationNote(bk)}` : ''}
                    </p>
                    {isActive(bk, nowMs) && bk.status === 'held' && (
                      <div className="hstack">
                        <button type="button" disabled={busy} onClick={() => void confirm(bk)} data-testid="bookings-confirm">Confirm booking</button>
                        <button type="button" className="outline" disabled={busy} onClick={() => setConfirmCancel(bk.id)} data-testid="bookings-cancel-btn">Cancel hold</button>
                      </div>
                    )}
                    {isActive(bk, nowMs) && bk.status === 'confirmed' && (
                      <button type="button" className="outline" disabled={busy} onClick={() => setConfirmCancel(bk.id)} data-testid="bookings-cancel-btn">Cancel booking</button>
                    )}
                    {confirmCancel === bk.id && (
                      <div role="group" aria-label="Confirm cancellation" data-testid="bookings-cancel-confirm" className="stack">
                        <p className="small-text">
                          {bk.status === 'held'
                            ? 'Cancelling a hold is free.'
                            : 'Cancelling a confirmed booking close to its start may cost the cancellation fee set in the project spec. The exact fee is recorded and shown here once it is cancelled.'}
                        </p>
                        <label htmlFor={`${reasonId}-${bk.id}`}>Reason (optional)</label>
                        <input id={`${reasonId}-${bk.id}`} value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} data-testid="bookings-reason" />
                        <div className="hstack">
                          <button type="button" disabled={busy} onClick={() => void cancel(bk)} data-testid="bookings-cancel-yes">Yes, cancel</button>
                          <button type="button" className="outline" onClick={() => setConfirmCancel(null)} data-testid="bookings-cancel-no">Keep it</button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
                {selected.label === 'Taken' && <p className="small-text muted" data-testid="bookings-taken">This slot is taken (possibly by a booking you cannot see).</p>}

                {selected.bookable && resource.mode === 'slot' && (
                  <form className="stack" onSubmit={(e) => { e.preventDefault(); void hold(selected.startsAt, selected.endsAt) }} data-testid="bookings-hold-form" aria-label="Create a hold">
                    <label htmlFor={custId}>Customer reference (optional)</label>
                    <input id={custId} value={customer} maxLength={128} onChange={(e) => setCustomer(e.target.value)} data-testid="bookings-customer" />
                    <label htmlFor={notesId}>Notes (optional)</label>
                    <input id={notesId} value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} data-testid="bookings-notes" />
                    <button type="submit" disabled={busy} data-testid="bookings-hold">{busy ? 'Working…' : 'Hold this slot'}</button>
                  </form>
                )}

              </div>
            )}
          </div>
        </>
      )}
    </section>
  )
}

function RangeForm({ resource, call, busy, onHold, tz }: {
  resource: Resource; call: (m: string, p: string, b?: unknown) => Promise<{ status: number; json: unknown }>; busy: boolean
  onHold: (s: string, e: string, extra?: Record<string, unknown>) => Promise<void>; tz: string
}) {
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [qty, setQty] = useState('1')
  const [cap, setCap] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const id = useId()
  const s = parseLocalInput(start, tz), e = parseLocalInput(end, tz)
  const q = Number(qty)
  const valid = !!s && !!e && Date.parse(e) > Date.parse(s) && (resource.mode !== 'pool' || (Number.isInteger(q) && q >= 1))

  async function capacity() {
    setErr(null); setCap(null)
    if (!s || !e) { setErr('Enter a start and an end first.'); return }
    try {
      const r = await call('GET', `/booking/resources/${encodeURIComponent(resource.id)}/capacity?starts_at=${encodeURIComponent(s)}&ends_at=${encodeURIComponent(e)}`)
      if (r.status === 200) { const j = r.json as { capacity: number; booked: number; free: number }; setCap(`Capacity ${j.capacity}, booked ${j.booked}, free ${j.free} in that window.`) }
      else setErr(bookingErrorMessage(r.status, r.json))
    } catch (x) { setErr(msg(x, 'Could not reach the booking API')) }
  }

  return (
    <form className="stack" onSubmit={(ev) => { ev.preventDefault(); if (valid && s && e) void onHold(s, e, resource.mode === 'pool' ? { quantity: q } : {}) }} data-testid="bookings-range-form" aria-label={`Book ${resource.mode} resource`}>
      <h2>New {resource.mode === 'pool' ? 'pool' : 'range'} booking (times in {tz})</h2>
      <label htmlFor={`${id}-s`}>Starts</label>
      <input id={`${id}-s`} type="datetime-local" value={start} onChange={(ev) => setStart(ev.target.value)} data-testid="bookings-start" />
      <label htmlFor={`${id}-e`}>Ends</label>
      <input id={`${id}-e`} type="datetime-local" value={end} onChange={(ev) => setEnd(ev.target.value)} data-testid="bookings-end" />
      {resource.mode === 'pool' && (
        <>
          <label htmlFor={`${id}-q`}>Quantity</label>
          <input id={`${id}-q`} type="number" min={1} step={1} value={qty} onChange={(ev) => setQty(ev.target.value)} data-testid="bookings-qty" />
        </>
      )}
      <div className="hstack">
        <button type="button" className="outline" onClick={() => void capacity()} data-testid="bookings-capacity">Check capacity</button>
        <button type="submit" disabled={busy || !valid} data-testid="bookings-range-hold">Create hold</button>
      </div>
      {cap && <p role="status" data-testid="bookings-capacity-result">{cap}</p>}
      {err && <p role="alert" className="error-text" data-testid="bookings-capacity-error">{err}</p>}
    </form>
  )
}
