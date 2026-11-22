import { describe, expect, it } from 'vitest'
import {
  applyBooking, buildResourceCreate, buildResourceUpdate, describeCancellation, formatMinorAmount, formatSchedule, freeGaps, groupSlots, kindToSpec, newKindForm,
  parseInteger, parseRoles, parseSchedule, rulesFormOf, saveErrorMessage, validateKind, validateRange, validateRules, type ResourceRow,
} from './bookingAdminLogic'

const RULES = rulesFormOf({})
describe('parsing', () => {
  it('parses strict integers and refuses floats, exponents and blanks', () => {
    expect(parseInteger('42')).toBe(42)
    for (const bad of ['', '1.5', '1e3', ' 5', 'abc', '99999999999999999999']) expect(parseInteger(bad)).toBeNull()
  })
  it('splits roles on commas and spaces and dedupes', () => expect(parseRoles('admin, staff  admin,,ops')).toEqual(['admin', 'staff', 'ops']))
  it('round-trips a schedule and checks windows like the backend', () => {
    const r = parseSchedule('mon 09:00-12:00, 13:00-17:00\ntue 08:00-10:00')
    expect(r.error).toBeNull()
    expect(formatSchedule(r.schedule)).toBe('mon 09:00-12:00, 13:00-17:00\ntue 08:00-10:00')
    expect(parseSchedule('xyz 09:00-10:00').error).toMatch(/weekday/)
    expect(parseSchedule('mon 10:00-09:00').error).toMatch(/before the end/)
    expect(parseSchedule('mon 09:00-12:00, 11:00-13:00').error).toMatch(/overlap/)
    expect(parseSchedule('mon 09:00-09:10', 30).error).toMatch(/shorter/)
    expect(parseSchedule('mon 09:00-10:00\nmon 11:00-12:00').error).toMatch(/twice/)
    expect(parseSchedule('mon 25:00-26:00').error).not.toBeNull()
  })
})

describe('rules validation (mirrors validation_booking.py)', () => {
  it('accepts the defaults', () => expect(validateRules(RULES)).toEqual({}))
  it('enforces ranges, integer fee and currency', () => {
    const e = validateRules({ ...RULES, hold_ttl_seconds: '0', max_horizon_days: '731', free_until_hours: '8761', fee_minor: '12.5', currency: 'usd' })
    expect(Object.keys(e).sort()).toEqual(['currency', 'fee_minor', 'free_until_hours', 'hold_ttl_seconds', 'max_horizon_days'])
    expect(validateRules({ ...RULES, fee_minor: String(2 ** 53) }).fee_minor).toBeTruthy()
    expect(validateRules({ ...RULES, fee_minor: String(2 ** 53 - 1) }).fee_minor).toBeUndefined()
  })
  it('needs a manager role, allows empty read/book roles', () => {
    expect(validateRules({ ...RULES, manage_roles: ' ' }).manage_roles).toMatch(/at least one/)
    expect(validateRules({ ...RULES, read_roles: '', book_roles: '' })).toEqual({})
    expect(validateRules({ ...RULES, read_roles: 'a b!' }).read_roles).toMatch(/not a valid/)
  })
  it('validates kinds per mode', () => {
    expect(validateKind(newKindForm('slot'), 0, [])).toMatchObject({ 'kinds[0].name': expect.any(String) })
    const ok = { ...newKindForm('slot'), name: 'room' }
    expect(validateKind(ok, 0, [])).toEqual({})
    expect(validateKind(ok, 0, ['room'])['kinds[0].name']).toMatch(/twice/)
    expect(validateKind({ ...ok, timezone: 'Mars/Base' }, 0, [])['kinds[0].timezone']).toBeTruthy()
    expect(validateKind({ ...ok, slot_minutes: '4' }, 0, [])['kinds[0].slot_minutes']).toBeTruthy()
    expect(validateKind({ ...ok, schedule: '' }, 0, [])['kinds[0].schedule']).toMatch(/at least one/)
    const pool = { ...newKindForm('pool'), name: 'seat', capacity: '0' }
    expect(validateKind(pool, 1, [])['kinds[1].capacity']).toBeTruthy()
    expect(validateKind({ ...pool, capacity: '5', min_minutes: '60', max_minutes: '30' }, 1, [])['kinds[1].min_minutes']).toBeTruthy()
  })
})

describe('saving into the packs block', () => {
  it('keeps the other packs and unknown booking keys, writes integers', () => {
    const packs = { money: { x: 1 }, booking: { future_key: true, kinds: [], cancellation: { extra: 1 } } }
    const out = applyBooking(packs, { ...RULES, fee_minor: '2500', currency: 'EUR', own_only: true, read_roles: 'a, b' }, [kindToSpec({ ...newKindForm('pool'), name: 'seat', capacity: '4' })]) as Record<string, any>
    expect(out.money).toEqual({ x: 1 })
    expect(out.booking.future_key).toBe(true)
    expect(out.booking.cancellation).toEqual({ extra: 1, free_until_hours: 24, fee_minor: 2500, currency: 'EUR' })
    expect(out.booking.read_roles).toEqual(['a', 'b'])
    expect(out.booking.own_only).toBe(true)
    expect(out.booking.kinds[0]).toMatchObject({ name: 'seat', mode: 'pool', capacity: 4, schedule: {} })
    expect(Number.isInteger(out.booking.cancellation.fee_minor)).toBe(true)
  })
  it('formats money and the cancellation sentence with integer maths', () => {
    expect(formatMinorAmount(2500, 'USD')).toBe('USD 25.00')
    expect(formatMinorAmount(5, 'USD')).toBe('USD 0.05')
    expect(formatMinorAmount(500, 'JPY')).toBe('JPY 500')
    expect(describeCancellation('24', '2500', 'USD')).toBe('Cancelling at least 24 hours before the start is free; later it costs USD 25.00.')
    expect(describeCancellation('x', '1', 'USD')).toBe('')
  })
  it('explains 409 and 422 with issue paths', () => {
    expect(saveErrorMessage(409, 'x', [])).toMatch(/Someone else saved/)
    expect(saveErrorMessage(422, 'Invalid spec.', [{ path: 'packs.booking.read_roles', message: 'unknown role' }])).toBe('Invalid spec. packs.booking.read_roles: unknown role')
  })
})

describe('resource payloads', () => {
  const base = { kind: 'room', name: ' Room 1 ', timezone: '', capacity: '', schedule: '', active: true }
  it('sends only what the mode allows', () => {
    expect(buildResourceCreate(base, 'slot').body).toEqual({ kind: 'room', name: 'Room 1', active: true })
    expect(buildResourceCreate({ ...base, capacity: '5', schedule: 'mon 09:00-10:00' }, 'range').body).toEqual({ kind: 'room', name: 'Room 1', active: true })
    expect(buildResourceCreate({ ...base, capacity: '5' }, 'pool').body).toMatchObject({ capacity: 5 })
    expect(buildResourceCreate({ ...base, schedule: 'mon 09:00-10:00' }, 'slot').body).toMatchObject({ schedule: { mon: [{ start: '09:00', end: '10:00' }] } })
  })
  it('refuses bad input', () => {
    expect(buildResourceCreate({ ...base, name: ' ' }, 'slot').error).toBeTruthy()
    expect(buildResourceCreate({ ...base, timezone: 'Nope/Zone' }, 'slot').error).toMatch(/timezone/)
    expect(buildResourceCreate({ ...base, capacity: '1.5' }, 'pool').error).toMatch(/Capacity/)
    expect(buildResourceCreate({ ...base, kind: '' }, null).error).toBeTruthy()
  })
  const row: ResourceRow = { id: 'r', kind: 'room', mode: 'slot', name: 'A', timezone: 'UTC', slot_minutes: 30, schedule: { mon: [{ start: '09:00', end: '10:00' }] }, capacity: 1, min_minutes: null, max_minutes: null, active: true }
  it('patches only the changed fields', () => {
    expect(buildResourceUpdate(row, { name: 'A', timezone: 'UTC', schedule: formatSchedule(row.schedule), active: true }).error).toBe('Nothing changed.')
    expect(buildResourceUpdate(row, { name: 'B', timezone: 'UTC', schedule: formatSchedule(row.schedule), active: false }).body).toEqual({ name: 'B', active: false })
    expect(buildResourceUpdate(row, { name: 'A', timezone: 'UTC', schedule: '', active: true }).error).toMatch(/at least one/)
  })
})

describe('availability helpers', () => {
  it('validates the date range (max 31 days)', () => {
    expect(validateRange('2026-01-01', '2026-01-31')).toBeNull()
    expect(validateRange('2026-01-01', '2026-02-01')).toMatch(/31/)
    expect(validateRange('2026-01-05', '2026-01-01')).toMatch(/before/)
    expect(validateRange('x', '2026-01-01')).toMatch(/dates/)
  })
  it('groups slots by local day in the resource zone', () => {
    const d = groupSlots([
      { starts_at: '2026-01-01T23:30:00Z', ends_at: '2026-01-02T00:00:00Z', free: true },
      { starts_at: '2026-01-01T09:00:00Z', ends_at: '2026-01-01T09:30:00Z', free: false },
      { starts_at: '2026-01-01T09:30:00Z', ends_at: '2026-01-01T10:00:00Z', free: true },
    ], 'Asia/Tokyo')
    expect(d).toEqual([{ day: '2026-01-01', free: ['18:30'], taken: ['18:00'] }, { day: '2026-01-02', free: ['08:30'], taken: [] }])
  })
  it('computes free gaps around bookings', () => {
    const H = (h: number) => Date.UTC(2026, 0, 1, h)
    const g = freeGaps([{ starts_at: new Date(H(10)).toISOString(), ends_at: new Date(H(11)).toISOString() }, { starts_at: new Date(H(10)).toISOString(), ends_at: new Date(H(12)).toISOString() }], H(8), H(14))
    expect(g.map((x) => [Date.parse(x.from), Date.parse(x.to)])).toEqual([[H(8), H(10)], [H(12), H(14)]])
    expect(freeGaps([{ starts_at: new Date(H(7)).toISOString(), ends_at: new Date(H(15)).toISOString() }], H(8), H(14))).toEqual([])
  })
})
