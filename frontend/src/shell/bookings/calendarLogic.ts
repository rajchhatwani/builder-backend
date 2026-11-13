/** Pure logic of the Booking calendar (F5-3). Times travel as ISO-8601 instants; display is always in the RESOURCE's IANA time
 *  zone (Intl, no offset guessing). Fees are integer minor units formatted with BigInt maths (never float). */
import { formatMinor, type Minor } from '../ledger/ledgerLogic'

export type Mode = 'slot' | 'range' | 'pool'
export type BookingStatus = 'held' | 'confirmed' | 'cancelled' | 'expired'
export interface Resource { id: string; kind: string; mode: Mode; name: string; timezone: string; slot_minutes: number | null; capacity: number; min_minutes: number | null; max_minutes: number | null; active: boolean }
export interface Slot { starts_at: string; ends_at: string; free: boolean }
export interface Booking {
  id: string; resource_id: string; resource_name: string; kind: string; mode: Mode; status: BookingStatus; starts_at: string; ends_at: string
  quantity: number; hold_expires_at: string | null; customer_ref: string | null; notes: string | null
  cancel_fee_minor: Minor | null; fee_currency: string | null; cancelled_at: string | null; confirmed_at: string | null
}

/** Fee fields are quoted before JSON.parse so a huge integer keeps every digit. */
const FEE_KEYS = /("(?:cancel_fee_minor|fee_minor)"\s*:\s*)(-?\d+)/g
export const parseBookingJson = (text: string): unknown => JSON.parse(text.replace(FEE_KEYS, '$1"$2"'))

// ---------------------------------------------------------------- dates and time zones

export const isDate = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(`${s}T00:00:00Z`)) && new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s

export function isValidTimeZone(tz: string): boolean {
  try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); return true } catch { return false }
}

const fmtCache = new Map<string, Intl.DateTimeFormat>()
function fmt(tz: string): Intl.DateTimeFormat {
  let f = fmtCache.get(tz)
  if (!f) { f = new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }); fmtCache.set(tz, f) }
  return f
}

export interface LocalParts { date: string; time: string }
/** Wall-clock date (YYYY-MM-DD) and time (HH:MM) of an instant in `tz`. Falls back to UTC for an unknown zone. */
export function localParts(instant: string | number, tz: string): LocalParts {
  const ms = typeof instant === 'number' ? instant : Date.parse(instant)
  if (!Number.isFinite(ms)) return { date: '', time: '' }
  const zone = isValidTimeZone(tz) ? tz : 'UTC'
  const p: Record<string, string> = {}
  for (const part of fmt(zone).formatToParts(new Date(ms))) p[part.type] = part.value
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour === '24' ? '00' : p.hour}:${p.minute}` }
}

/** Offset of `tz` from UTC at an instant, in whole minutes (positive east). */
function offsetMinutes(ms: number, tz: string): number {
  const lp = localParts(Math.floor(ms / 60_000) * 60_000, tz)
  const asUtc = Date.parse(`${lp.date}T${lp.time}:00Z`)
  return Math.round((asUtc - Math.floor(ms / 60_000) * 60_000) / 60_000)
}

/** Wall-clock date+time in `tz` to a UTC ISO instant ("...Z"). Ambiguous times (fall-back hour) resolve to the first occurrence;
 *  times that do not exist (spring-forward gap) resolve forward by the gap length. Null when the input is malformed. */
export function zonedToUtc(date: string, time: string, tz: string): string | null {
  if (!isDate(date) || !/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) return null
  const zone = isValidTimeZone(tz) ? tz : 'UTC'
  const naive = Date.parse(`${date}T${time}:00Z`)
  const DAY_MS = 86_400_000
  const before = naive - offsetMinutes(naive - DAY_MS, zone) * 60_000
  const after = naive - offsetMinutes(naive + DAY_MS, zone) * 60_000
  const ok = (ms: number) => { const p = localParts(ms, zone); return p.date === date && p.time === time }
  const valid = [before, after].filter(ok)
  const ms = valid.length ? Math.min(...valid) : before
  return new Date(ms).toISOString().replace('.000Z', 'Z')
}

/** "2026-12-01T09:30" (a datetime-local value) in the resource zone to a UTC ISO instant. */
export function parseLocalInput(v: string, tz: string): string | null {
  const m = v.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})$/)
  return m ? zonedToUtc(m[1], m[2], tz) : null
}

export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}
/** Day of week with Monday = 0 .. Sunday = 6 for a civil date. */
export const weekdayIndex = (date: string): number => (new Date(`${date}T00:00:00Z`).getUTCDay() + 6) % 7
export const mondayOf = (date: string): string => addDays(date, -weekdayIndex(date))

export interface WeekRange { from: string; to: string; days: string[] }
/** The Monday-to-Sunday week containing `anchor` (civil dates, so no time zone or DST can shift it). `to` is inclusive. */
export function weekRange(anchor: string): WeekRange {
  const from = mondayOf(anchor)
  const days = Array.from({ length: 7 }, (_, i) => addDays(from, i))
  return { from, to: days[6], days }
}

const DAY = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** "Mon 1 Dec" for a civil date. */
export const formatDay = (date: string): string => `${DAY[weekdayIndex(date)]} ${Number(date.slice(8, 10))} ${MON[Number(date.slice(5, 7)) - 1]}`
/** "Mon 1 Dec 09:00" of an instant in the resource zone. */
export function formatInstant(instant: string, tz: string): string {
  const p = localParts(instant, tz)
  return p.date ? `${formatDay(p.date)} ${p.time}` : 'unknown time'
}

/** Instants bounding a week for GET /booking/bookings?from&to (local midnight to local midnight of the next Monday). */
export function weekInstants(w: WeekRange, tz: string): { from: string; to: string } {
  return { from: zonedToUtc(w.from, '00:00', tz) ?? `${w.from}T00:00:00Z`, to: zonedToUtc(addDays(w.to, 1), '00:00', tz) ?? `${addDays(w.to, 1)}T00:00:00Z` }
}

// ---------------------------------------------------------------- overlap + states

/** Half-open [start, end) intervals: back-to-back never overlap. */
export function overlaps(a: { starts_at: string; ends_at: string }, b: { starts_at: string; ends_at: string }): boolean {
  const as = Date.parse(a.starts_at), ae = Date.parse(a.ends_at), bs = Date.parse(b.starts_at), be = Date.parse(b.ends_at)
  if (![as, ae, bs, be].every(Number.isFinite)) return false
  return as < be && bs < ae
}

/** A booking occupies time while confirmed, or held and not past its hold expiry. */
export const isActive = (b: Booking, nowMs: number): boolean =>
  b.status === 'confirmed' || (b.status === 'held' && (!b.hold_expires_at || Date.parse(b.hold_expires_at) > nowMs))

/** Pairs of active slot/range bookings of one resource that overlap (the server forbids this; the display flags it if it ever shows). */
export function findOverlaps(bookings: Booking[], nowMs: number): [Booking, Booking][] {
  const act = bookings.filter((b) => b.mode !== 'pool' && isActive(b, nowMs))
  const out: [Booking, Booking][] = []
  for (let i = 0; i < act.length; i++) for (let j = i + 1; j < act.length; j++) if (act[i].resource_id === act[j].resource_id && overlaps(act[i], act[j])) out.push([act[i], act[j]])
  return out
}

export type CellState = 'free' | 'held' | 'booked' | 'cancelled'
export interface Cell { key: string; day: string; time: string; startsAt: string; endsAt: string; state: CellState; label: string; bookable: boolean; booking: Booking | null; bookings: Booking[] }
export interface Grid { times: string[]; days: string[]; cells: (Cell | null)[][] }

const LABEL: Record<string, string> = { free: 'Free', held: 'Held', booked: 'Booked', cancelled: 'Cancelled', expired: 'Expired', taken: 'Taken' }

/** Week grid: one column per day, one row per distinct local start time. Cells come from the availability slots (free flag) and
 *  from bookings; the active booking decides the colour, otherwise the slot's free flag, otherwise the last cancelled/expired booking. */
export function buildGrid(days: string[], slots: Slot[], bookings: Booking[], tz: string, nowMs: number): Grid {
  type Raw = { starts: string; ends: string; slot: Slot | null; bookings: Booking[] }
  const raw = new Map<string, Raw>() // key = `${day}|${time}`
  const put = (instant: string, ends: string) => {
    const p = localParts(instant, tz)
    if (!p.date || !days.includes(p.date)) return null
    const key = `${p.date}|${p.time}`
    let r = raw.get(key)
    if (!r) { r = { starts: instant, ends, slot: null, bookings: [] }; raw.set(key, r) }
    return r
  }
  for (const s of slots) { const r = put(s.starts_at, s.ends_at); if (r) { r.slot = s; r.starts = s.starts_at; r.ends = s.ends_at } }
  for (const b of bookings) { const r = put(b.starts_at, b.ends_at); if (r) r.bookings.push(b) }
  const times = Array.from(new Set(Array.from(raw.keys()).map((k) => k.split('|')[1]))).sort()
  const cells: (Cell | null)[][] = times.map(() => days.map(() => null))
  for (const [key, r] of raw) {
    const [day, time] = key.split('|')
    const active = r.bookings.find((b) => isActive(b, nowMs)) ?? null
    const dead = [...r.bookings].filter((b) => !isActive(b, nowMs)).sort((a, b) => Date.parse(b.cancelled_at ?? b.starts_at) - Date.parse(a.cancelled_at ?? a.starts_at))[0] ?? null
    let state: CellState, label: string, booking: Booking | null
    if (active) { state = active.status === 'confirmed' ? 'booked' : 'held'; label = LABEL[state]; booking = active }
    else if (r.slot && !r.slot.free) { state = 'booked'; label = LABEL.taken; booking = null }
    else if (dead) { state = 'cancelled'; label = dead.status === 'expired' || dead.status === 'held' ? LABEL.expired : LABEL.cancelled; booking = dead }
    else { state = 'free'; label = LABEL.free; booking = null }
    const bookable = !active && (r.slot ? r.slot.free : false)
    cells[times.indexOf(time)][days.indexOf(day)] = { key, day, time, startsAt: r.starts, endsAt: r.ends, state, label, bookable, booking, bookings: r.bookings }
  }
  return { times, days, cells }
}

// ---------------------------------------------------------------- keyboard

export type NavKey = 'ArrowUp' | 'ArrowDown' | 'ArrowLeft' | 'ArrowRight' | 'Home' | 'End'
/** Next focusable grid position for an arrow/Home/End key, skipping empty cells in the key's direction; stays put at an edge. */
export function moveFocus(exists: boolean[][], r: number, c: number, key: string): [number, number] {
  const rows = exists.length, cols = rows ? exists[0].length : 0
  const step = (dr: number, dc: number): [number, number] => {
    let rr = r + dr, cc = c + dc
    while (rr >= 0 && rr < rows && cc >= 0 && cc < cols) { if (exists[rr][cc]) return [rr, cc]; rr += dr; cc += dc }
    return [r, c]
  }
  switch (key) {
    case 'ArrowUp': return step(-1, 0)
    case 'ArrowDown': return step(1, 0)
    case 'ArrowLeft': return step(0, -1)
    case 'ArrowRight': return step(0, 1)
    case 'Home': { const i = exists[r]?.findIndex(Boolean) ?? -1; return i >= 0 ? [r, i] : [r, c] }
    case 'End': { const row = exists[r] ?? []; for (let i = row.length - 1; i >= 0; i--) if (row[i]) return [r, i]; return [r, c] }
    default: return [r, c]
  }
}

// ---------------------------------------------------------------- money and errors

const EXPONENT: Record<string, number> = { JPY: 0, KRW: 0, VND: 0, CLP: 0, ISK: 0, UGX: 0, BHD: 3, KWD: 3, OMR: 3, JOD: 3, TND: 3 }
export const currencyExponent = (code: string | null | undefined): number => EXPONENT[(code ?? '').toUpperCase()] ?? 2
/** 2500 + "EUR" -> "EUR 25.00"; 500 + "JPY" -> "JPY 500". Integer maths only; a missing currency prints the bare amount. */
export function formatFee(minor: Minor, currency: string | null | undefined): string {
  const amount = formatMinor(minor, currencyExponent(currency))
  return currency ? `${currency.toUpperCase()} ${amount}` : amount
}
/** Sentence about the fee recorded on a cancelled booking. */
export function cancellationNote(b: Pick<Booking, 'cancel_fee_minor' | 'fee_currency'>): string {
  if (b.cancel_fee_minor === null || b.cancel_fee_minor === undefined) return 'Cancelled.'
  const zero = typeof b.cancel_fee_minor === 'bigint' ? b.cancel_fee_minor === 0n : /^-?0+$/.test(String(b.cancel_fee_minor))
  return zero ? 'Cancelled with no fee.' : `Cancelled. Cancellation fee recorded: ${formatFee(b.cancel_fee_minor, b.fee_currency)}.`
}

export function bookingErrorMessage(status: number, body: unknown): string {
  const b = (typeof body === 'object' && body !== null ? body : {}) as { code?: unknown; message?: unknown }
  const code = typeof b.code === 'string' ? b.code : ''
  switch (code) {
    case 'slot_taken': return 'That slot was just taken by someone else. Pick another slot.'
    case 'capacity_exceeded': return 'Not enough capacity left for that time. Lower the quantity or pick another time.'
    case 'hold_expired': return 'Your hold expired before it was confirmed, so the slot was released. Start again.'
    case 'outside_availability': return 'That time is outside the resource\'s availability (not a scheduled slot, in the past, or too far ahead).'
    case 'invalid_transition': return 'This booking can no longer be changed that way (it was already confirmed, cancelled or expired).'
    case 'idempotency_conflict': return 'That request key was already used for a different booking. Reload and try again.'
    case 'resource_inactive': return 'This resource is switched off and cannot be booked.'
    case 'invalid_range': return 'The end must be after the start and within the allowed length.'
    case 'invalid_quantity': return 'The quantity is not valid for this resource.'
    case 'invalid_time': return 'The time is not valid (it needs a date and a time).'
    case 'not_slot_resource': return 'This resource is not booked by fixed slots.'
    case 'not_pool_resource': return 'Only pool resources have a capacity count.'
    case 'forbidden': return 'You may only change your own bookings.'
    case 'not_found': return 'That booking or resource no longer exists.'
  }
  if (status === 401) return 'The token was not accepted (missing, wrong or expired).'
  if (status === 403) return 'Your role may not do this (the spec lists book, manage and read roles).'
  if (status === 410) return 'Your hold expired before it was confirmed, so the slot was released. Start again.'
  return (typeof b.message === 'string' && b.message) || `The booking API answered ${status}.`
}

