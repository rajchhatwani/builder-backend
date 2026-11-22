// Pure helpers for the booking admin page: validation mirrors SpecBookingPack (app/core/spec_models.py) and
// app/core/validation_booking.py; resource payloads mirror the generated /booking schemas. No React, no network.
import { addDays, isDate, isValidTimeZone, localParts, type Booking, type Mode, type Slot } from './calendarLogic'

export const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const
export const MAX_KINDS = 20
export const MAX_CAPACITY = 100_000
export const MAX_FEE_MINOR = 2 ** 53 - 1
export const MAX_AVAILABILITY_DAYS = 31
const KIND_NAME = /^[a-z][a-z0-9_]{0,39}$/
const HHMM = /^([01]\d|2[0-3]):([0-5]\d)$/
const CURRENCY = /^[A-Z]{3}$/
const ROLE = /^[A-Za-z0-9_.:-]{1,64}$/

export type Obj = Record<string, unknown>
export type Window = { start: string; end: string }
export type Schedule = Record<string, Window[]>
export type Errors = Record<string, string>

/** Strict non-negative integer parse of a form field ('' / '1.5' / '1e3' / ' 5' -> null). Safe-integer range only. */
export function parseInteger(v: string): number | null {
  if (!/^-?\d{1,17}$/.test(v)) return null
  const n = Number(v)
  return Number.isSafeInteger(n) ? n : null
}

export const parseRoles = (text: string): string[] => {
  const out: string[] = []
  for (const r of text.split(/[\s,]+/)) if (r && !out.includes(r)) out.push(r)
  return out
}

export const minutesOf = (v: string): number | null => {
  const m = HHMM.exec(v)
  return m ? Number(m[1]) * 60 + Number(m[2]) : null
}

// ---------------------------------------------------------------- schedule text: "mon 09:00-12:00, 13:00-17:00" per line

export function formatSchedule(s: Schedule | null | undefined): string {
  if (!s) return ''
  return WEEKDAYS.filter((d) => s[d]?.length).map((d) => `${d} ${s[d].map((w) => `${w.start}-${w.end}`).join(', ')}`).join('\n')
}

/** Parses the schedule text and checks it like check_schedule (weekday keys, HH:MM, start < end, no overlap, window fits a slot). */
export function parseSchedule(text: string, slotMinutes?: number | null): { schedule: Schedule; error: string | null } {
  const schedule: Schedule = {}
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const m = /^([a-z]{3})\s+(.+)$/.exec(line)
    if (!m || !(WEEKDAYS as readonly string[]).includes(m[1])) return { schedule: {}, error: `"${line.slice(0, 30)}": start with a weekday (mon, tue, wed, thu, fri, sat, sun).` }
    if (schedule[m[1]]) return { schedule: {}, error: `${m[1]} appears twice: put all its windows on one line.` }
    const spans: [number, number][] = []
    const wins: Window[] = []
    for (const part of m[2].split(',')) {
      const w = /^\s*(\d\d:\d\d)\s*-\s*(\d\d:\d\d)\s*$/.exec(part)
      const a = w ? minutesOf(w[1]) : null, b = w ? minutesOf(w[2]) : null
      if (!w || a === null || b === null || a >= b) return { schedule: {}, error: `${m[1]}: "${part.trim().slice(0, 20)}" must be HH:MM-HH:MM (24 h) with the start before the end.` }
      if (slotMinutes && b - a < slotMinutes) return { schedule: {}, error: `${m[1]}: ${w[1]}-${w[2]} is shorter than one ${slotMinutes} minute slot.` }
      spans.push([a, b]); wins.push({ start: w[1], end: w[2] })
    }
    spans.sort((x, y) => x[0] - y[0])
    for (let i = 0; i < spans.length - 1; i++) if (spans[i][1] > spans[i + 1][0]) return { schedule: {}, error: `${m[1]}: the windows must not overlap.` }
    schedule[m[1]] = wins
  }
  return { schedule, error: null }
}

// ---------------------------------------------------------------- kinds (spec.packs.booking.kinds)

export interface KindForm { name: string; mode: Mode; timezone: string; slot_minutes: string; capacity: string; min_minutes: string; max_minutes: string; schedule: string }

export function kindFormOf(k: Obj): KindForm {
  return {
    name: String(k.name ?? ''), mode: (['slot', 'range', 'pool'].includes(String(k.mode)) ? k.mode : 'slot') as Mode, timezone: String(k.timezone ?? 'UTC'),
    slot_minutes: String(k.slot_minutes ?? 30), capacity: String(k.capacity ?? 1), min_minutes: String(k.min_minutes ?? 15), max_minutes: String(k.max_minutes ?? 43200),
    schedule: formatSchedule(k.schedule as Schedule | undefined),
  }
}

export const newKindForm = (mode: Mode = 'slot'): KindForm => ({
  name: '', mode, timezone: 'UTC', slot_minutes: '30', capacity: '1', min_minutes: '15', max_minutes: '43200',
  schedule: mode === 'slot' ? 'mon 09:00-17:00\ntue 09:00-17:00\nwed 09:00-17:00\nthu 09:00-17:00\nfri 09:00-17:00' : '',
})

export function validateKind(f: KindForm, i: number, others: string[]): Errors {
  const e: Errors = {}
  const p = `kinds[${i}]`
  if (!KIND_NAME.test(f.name)) e[`${p}.name`] = 'A kind name is lower case letters, digits and _ (starts with a letter, at most 40).'
  else if (others.includes(f.name)) e[`${p}.name`] = 'A resource kind is declared twice.'
  if (!isValidTimeZone(f.timezone)) e[`${p}.timezone`] = `${f.timezone.slice(0, 40)} is not an IANA timezone.`
  if (f.mode === 'slot') {
    const sm = parseInteger(f.slot_minutes)
    if (sm === null || sm < 5 || sm > 1440) e[`${p}.slot_minutes`] = 'Slot length is 5 to 1440 minutes.'
    const r = parseSchedule(f.schedule, sm !== null && sm >= 5 && sm <= 1440 ? sm : null)
    if (r.error) e[`${p}.schedule`] = r.error
    else if (Object.keys(r.schedule).length === 0) e[`${p}.schedule`] = 'A slot kind needs at least one opening window.'
  } else {
    const lo = parseInteger(f.min_minutes), hi = parseInteger(f.max_minutes)
    if (lo === null || hi === null || lo < 1 || lo > hi || hi > 525_600) e[`${p}.min_minutes`] = 'Minimum and maximum minutes: 1 <= minimum <= maximum <= 525600.'
    if (f.mode === 'pool') {
      const c = parseInteger(f.capacity)
      if (c === null || c < 1 || c > MAX_CAPACITY) e[`${p}.capacity`] = `Capacity is 1 to ${MAX_CAPACITY}.`
    }
  }
  return e
}

/** Spec object of a kind: starts from the stored one (unknown keys survive) and sets the fields this mode allows. */
export function kindToSpec(f: KindForm, base: Obj = {}): Obj {
  const out: Obj = { ...base, name: f.name, mode: f.mode, timezone: f.timezone }
  if (f.mode === 'slot') {
    out.slot_minutes = parseInteger(f.slot_minutes); out.schedule = parseSchedule(f.schedule).schedule; out.capacity = 1
  } else {
    out.schedule = {}; out.min_minutes = parseInteger(f.min_minutes); out.max_minutes = parseInteger(f.max_minutes)
    out.capacity = f.mode === 'pool' ? parseInteger(f.capacity) : 1
  }
  return out
}

// ---------------------------------------------------------------- rules (roles, hold, horizon, cancellation)

export interface RulesForm {
  read_roles: string; book_roles: string; manage_roles: string; own_only: boolean
  hold_ttl_seconds: string; max_horizon_days: string; free_until_hours: string; fee_minor: string; currency: string
}

const roleText = (v: unknown, d: string[]) => (Array.isArray(v) ? v : d).join(', ')
export function rulesFormOf(b: Obj): RulesForm {
  const c = (b.cancellation ?? {}) as Obj
  return {
    read_roles: roleText(b.read_roles, ['admin']), book_roles: roleText(b.book_roles, ['admin']), manage_roles: roleText(b.manage_roles, ['admin']), own_only: b.own_only === true,
    hold_ttl_seconds: String(b.hold_ttl_seconds ?? 600), max_horizon_days: String(b.max_horizon_days ?? 365),
    free_until_hours: String(c.free_until_hours ?? 24), fee_minor: String(c.fee_minor ?? 0), currency: String(c.currency ?? 'USD'),
  }
}

export function validateRules(f: RulesForm): Errors {
  const e: Errors = {}
  for (const k of ['read_roles', 'book_roles', 'manage_roles'] as const) {
    const bad = parseRoles(f[k]).find((r) => !ROLE.test(r))
    if (bad) e[k] = `"${bad.slice(0, 20)}" is not a valid role name.`
  }
  if (parseRoles(f.manage_roles).length === 0) e.manage_roles = 'manage_roles needs at least one role (an empty list would make nobody a manager).'
  const range = (k: keyof RulesForm, lo: number, hi: number, what: string) => {
    const n = parseInteger(String(f[k])); if (n === null || n < lo || n > hi) e[k] = `${what}: a whole number from ${lo} to ${hi}.`
  }
  range('hold_ttl_seconds', 1, 86_400, 'Hold time (seconds)')
  range('max_horizon_days', 1, 730, 'Booking horizon (days)')
  range('free_until_hours', 0, 8760, 'Free cancellation window (hours)')
  const fee = parseInteger(f.fee_minor)
  if (fee === null || fee < 0 || fee > MAX_FEE_MINOR) e.fee_minor = 'Cancellation fee: a whole number of minor units (cents), 0 or more. Decimals are not allowed.'
  if (!CURRENCY.test(f.currency)) e.currency = 'Currency is a 3 letter upper case code such as USD.'
  return e
}

/** New `packs` value: every other pack and every other booking key (e.g. unknown future keys) is kept untouched. */
export function applyBooking(packs: Obj | null, rules: RulesForm, kinds: Obj[]): Obj {
  const booking = ((packs?.booking ?? {}) as Obj)
  return {
    ...(packs ?? {}),
    booking: {
      ...booking, kinds,
      hold_ttl_seconds: parseInteger(rules.hold_ttl_seconds), max_horizon_days: parseInteger(rules.max_horizon_days),
      cancellation: { ...((booking.cancellation ?? {}) as Obj), free_until_hours: parseInteger(rules.free_until_hours), fee_minor: parseInteger(rules.fee_minor), currency: rules.currency },
      read_roles: parseRoles(rules.read_roles), book_roles: parseRoles(rules.book_roles), manage_roles: parseRoles(rules.manage_roles), own_only: rules.own_only,
    },
  }
}

/** Whole-hour summary of the cancellation rule for display. */
export function describeCancellation(hours: string, fee: string, currency: string): string {
  const h = parseInteger(hours), f = parseInteger(fee)
  if (h === null || f === null) return ''
  const amt = f === 0 ? 'free' : `a flat fee of ${formatMinorAmount(f, currency)}`
  return h === 0 ? `Cancelling is ${amt} only before the start.` : `Cancelling at least ${h} hour${h === 1 ? '' : 's'} before the start is free; later it costs ${f === 0 ? 'nothing' : formatMinorAmount(f, currency)}.`
}

const EXPONENT: Record<string, number> = { JPY: 0, KRW: 0, VND: 0, CLP: 0, ISK: 0, UGX: 0, PYG: 0, RWF: 0, XAF: 0, XOF: 0, XPF: 0, BHD: 3, KWD: 3, JOD: 3, OMR: 3, TND: 3 }
/** Integer minor units -> "USD 25.00" with string maths only (never a float). */
export function formatMinorAmount(minor: number, currency: string): string {
  const ex = EXPONENT[currency] ?? 2
  const s = String(Math.abs(minor)).padStart(ex + 1, '0')
  const body = ex === 0 ? s : `${s.slice(0, -ex)}.${s.slice(-ex)}`
  return `${currency} ${minor < 0 ? '-' : ''}${body}`
}

// ---------------------------------------------------------------- resources

export interface ResourceCreateForm { kind: string; name: string; timezone: string; capacity: string; schedule: string; active: boolean }
export interface ResourceRow { id: string; kind: string; mode: Mode; name: string; timezone: string; slot_minutes: number | null; schedule: Schedule | null; capacity: number; min_minutes: number | null; max_minutes: number | null; active: boolean }

/** POST /booking/resources body, or the first error. Only what the kind's mode allows is sent (the server refuses the rest). */
export function buildResourceCreate(f: ResourceCreateForm, mode: Mode | null): { body?: Obj; error?: string } {
  const name = f.name.trim()
  if (!f.kind) return { error: 'Pick a kind.' }
  if (!name || name.length > 120) return { error: 'Name is 1 to 120 characters.' }
  const body: Obj = { kind: f.kind, name, active: f.active }
  if (f.timezone.trim()) { if (!isValidTimeZone(f.timezone.trim())) return { error: `${f.timezone.slice(0, 40)} is not an IANA timezone.` }; body.timezone = f.timezone.trim() }
  if (mode === 'pool' && f.capacity.trim()) {
    const c = parseInteger(f.capacity.trim()); if (c === null || c < 1 || c > MAX_CAPACITY) return { error: `Capacity is 1 to ${MAX_CAPACITY}.` }
    body.capacity = c
  }
  if (mode === 'slot' && f.schedule.trim()) {
    const r = parseSchedule(f.schedule); if (r.error) return { error: r.error }
    body.schedule = r.schedule
  }
  return { body }
}

/** PATCH body: only changed fields. The kind, mode and capacity of a resource cannot be changed by the API. */
export function buildResourceUpdate(orig: ResourceRow, f: { name: string; timezone: string; schedule: string; active: boolean }): { body?: Obj; error?: string } {
  const body: Obj = {}
  const name = f.name.trim()
  if (!name || name.length > 120) return { error: 'Name is 1 to 120 characters.' }
  if (name !== orig.name) body.name = name
  if (f.timezone.trim() !== orig.timezone) { if (!isValidTimeZone(f.timezone.trim())) return { error: `${f.timezone.slice(0, 40)} is not an IANA timezone.` }; body.timezone = f.timezone.trim() }
  if (f.active !== orig.active) body.active = f.active
  if (orig.mode === 'slot' && f.schedule.trim() !== formatSchedule(orig.schedule)) {
    const r = parseSchedule(f.schedule, orig.slot_minutes); if (r.error) return { error: r.error }
    if (Object.keys(r.schedule).length === 0) return { error: 'A slot resource needs at least one opening window.' }
    body.schedule = r.schedule
  }
  return Object.keys(body).length ? { body } : { error: 'Nothing changed.' }
}

// ---------------------------------------------------------------- availability

export function validateRange(from: string, to: string): string | null {
  if (!isDate(from) || !isDate(to)) return 'Enter both dates (YYYY-MM-DD).'
  if (to < from) return 'The end date must not be before the start date.'
  if (addDays(from, MAX_AVAILABILITY_DAYS - 1) < to) return `At most ${MAX_AVAILABILITY_DAYS} days at a time.`
  return null
}

export interface DayAvailability { day: string; free: string[]; taken: string[] }
/** Slots grouped by local day (resource zone): sorted lists of start times, split free / taken. */
export function groupSlots(slots: Slot[], tz: string): DayAvailability[] {
  const days = new Map<string, DayAvailability>()
  for (const s of [...slots].sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at))) {
    const p = localParts(s.starts_at, tz)
    if (!p.date) continue
    const d = days.get(p.date) ?? { day: p.date, free: [], taken: [] }
    ;(s.free ? d.free : d.taken).push(p.time); days.set(p.date, d)
  }
  return [...days.values()].sort((a, b) => a.day.localeCompare(b.day))
}

/** Free gaps (ISO instants) of [fromMs, toMs) not covered by an active booking; for a range resource. */
export function freeGaps(bookings: Pick<Booking, 'starts_at' | 'ends_at'>[], fromMs: number, toMs: number): { from: string; to: string }[] {
  const busy = bookings.map((b) => [Date.parse(b.starts_at), Date.parse(b.ends_at)] as const).filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b)).sort((x, y) => x[0] - y[0])
  const out: { from: string; to: string }[] = []
  let cur = fromMs
  for (const [a, b] of busy) {
    if (b <= cur) continue
    if (a >= toMs) break
    if (a > cur) out.push({ from: new Date(cur).toISOString(), to: new Date(a).toISOString() })
    cur = Math.max(cur, b)
  }
  if (cur < toMs) out.push({ from: new Date(cur).toISOString(), to: new Date(toMs).toISOString() })
  return out
}

export function adminErrorMessage(status: number, body: unknown): string {
  const b = (typeof body === 'object' && body !== null ? body : {}) as { code?: unknown; message?: unknown }
  switch (b.code) {
    case 'unknown_kind': return 'That kind is not in the running project. Save the kinds, then regenerate and restart the preview.'
    case 'invalid_timezone': return 'That is not an IANA timezone (for example Europe/Berlin).'
    case 'invalid_schedule': return `The schedule was refused: ${typeof b.message === 'string' ? b.message : 'check the windows'}.`
    case 'invalid_capacity': return 'Only a pool resource has a capacity.'
    case 'not_found': return 'That resource no longer exists.'
    case 'invalid_range': return 'The date range is not valid (the end is before the start, or longer than 31 days).'
  }
  if (status === 401) return 'The preview session was not accepted. Sign in again.'
  if (status === 403) return 'Your role may not do this (managing resources needs a manage role from the spec).'
  return (typeof b.message === 'string' && b.message) || `The booking API answered ${status}.`
}

/** Text for a block-save failure: 409 stale version, 422 with the validator issues (path: message). */
export function saveErrorMessage(status: number, message: string, details: unknown): string {
  if (status === 409) return 'Someone else saved the packs first. Reload to see their version, then re-apply your change.'
  const issues = Array.isArray(details) ? details.slice(0, 5).map((d) => {
    const o = (typeof d === 'object' && d !== null ? d : {}) as Obj
    return typeof o.path === 'string' ? `${o.path}: ${String(o.message ?? o.code ?? '')}` : ''
  }).filter(Boolean) : []
  return issues.length ? `${message} ${issues.join('; ')}` : message
}
