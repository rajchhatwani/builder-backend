import { describe, expect, it } from 'vitest'
import {
  addDays, bookingErrorMessage, buildGrid, cancellationNote, currencyExponent, findOverlaps, formatDay, formatFee, formatInstant, isActive, isDate,
  isValidTimeZone, localParts, mondayOf, moveFocus, overlaps, parseBookingJson, parseLocalInput, weekInstants, weekRange, weekdayIndex, zonedToUtc,
  type Booking, type Slot,
} from './calendarLogic'

const NOW = Date.parse('2026-12-01T00:00:00Z')
const bk = (o: Partial<Booking>): Booking => ({
  id: 'b', resource_id: 'r1', resource_name: 'Dr A', kind: 'practitioner', mode: 'slot', status: 'confirmed', starts_at: '2026-12-01T08:00:00Z', ends_at: '2026-12-01T08:30:00Z',
  quantity: 1, hold_expires_at: null, customer_ref: null, notes: null, cancel_fee_minor: null, fee_currency: null, cancelled_at: null, confirmed_at: null, ...o,
})

describe('dates and weeks', () => {
  it('validates civil dates', () => {
    expect(isDate('2026-02-28')).toBe(true)
    expect(isDate('2026-02-30')).toBe(false)
    expect(isDate('2026-2-3')).toBe(false)
  })
  it('adds days across month, year and leap boundaries', () => {
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addDays('2028-03-01', -1)).toBe('2028-02-29')
    expect(addDays('2026-03-29', 7)).toBe('2026-04-05')
  })
  it('weeks run Monday to Sunday for every anchor weekday', () => {
    expect(weekdayIndex('2026-12-01')).toBe(1) // a Tuesday
    expect(mondayOf('2026-12-01')).toBe('2026-11-30')
    expect(mondayOf('2026-11-30')).toBe('2026-11-30')
    expect(mondayOf('2026-12-06')).toBe('2026-11-30') // Sunday
    const w = weekRange('2026-12-03')
    expect(w.from).toBe('2026-11-30'); expect(w.to).toBe('2026-12-06'); expect(w.days).toHaveLength(7)
    expect(weekRange('2026-12-31').days[0]).toBe('2026-12-28')
    expect(weekRange('2027-01-01').from).toBe('2026-12-28') // week spans the new year
  })
  it('formats days and instants without locale dependence', () => {
    expect(formatDay('2026-12-01')).toBe('Tue 1 Dec')
    expect(formatInstant('2026-12-01T08:00:00Z', 'Europe/Berlin')).toBe('Tue 1 Dec 09:00')
    expect(formatInstant('nope', 'UTC')).toBe('unknown time')
  })
})

describe('time zones', () => {
  it('knows valid and invalid zones', () => { expect(isValidTimeZone('Europe/Berlin')).toBe(true); expect(isValidTimeZone('Mars/Base')).toBe(false) })
  it('converts UTC to resource-local wall time across zones and the date line', () => {
    expect(localParts('2026-12-01T08:00:00Z', 'Europe/Berlin')).toEqual({ date: '2026-12-01', time: '09:00' })
    expect(localParts('2026-07-01T08:00:00Z', 'Europe/Berlin')).toEqual({ date: '2026-07-01', time: '10:00' })
    expect(localParts('2026-12-01T23:30:00Z', 'Asia/Tokyo')).toEqual({ date: '2026-12-02', time: '08:30' })
    expect(localParts('2026-12-01T03:00:00Z', 'America/Los_Angeles')).toEqual({ date: '2026-11-30', time: '19:00' })
    expect(localParts('2026-12-01T00:00:00Z', 'UTC')).toEqual({ date: '2026-12-01', time: '00:00' })
    expect(localParts('2026-12-01T00:00:00Z', 'Mars/Base')).toEqual({ date: '2026-12-01', time: '00:00' }) // falls back to UTC
    expect(localParts('bad', 'UTC')).toEqual({ date: '', time: '' })
  })
  it('handles half-hour zones', () => {
    expect(localParts('2026-12-01T00:00:00Z', 'Asia/Kolkata').time).toBe('05:30')
  })
  it('converts local wall time to UTC (winter, summer, negative offsets)', () => {
    expect(zonedToUtc('2026-12-01', '09:00', 'Europe/Berlin')).toBe('2026-12-01T08:00:00Z')
    expect(zonedToUtc('2026-07-01', '09:00', 'Europe/Berlin')).toBe('2026-07-01T07:00:00Z')
    expect(zonedToUtc('2026-12-01', '19:00', 'America/Los_Angeles')).toBe('2026-12-02T03:00:00Z')
    expect(zonedToUtc('2026-12-01', '00:00', 'Asia/Kolkata')).toBe('2026-11-30T18:30:00Z')
  })
  it('round-trips every hour around the DST changes of Berlin and New York', () => {
    for (const tz of ['Europe/Berlin', 'America/New_York']) {
      for (const start of ['2026-03-28', '2026-03-29', '2026-10-24', '2026-10-25', '2026-03-07', '2026-03-08', '2026-11-01']) {
        for (let h = 0; h < 24; h++) {
          const t = `${String(h).padStart(2, '0')}:00`
          const utc = zonedToUtc(start, t, tz)!
          const back = localParts(utc, tz)
          // gap hours resolve forward, everything else must round-trip exactly
          if (back.date === start && back.time === t) continue
          expect(['02:00', '03:00']).toContain(t)
        }
      }
    }
  })
  it('spring-forward gap resolves forward and fall-back ambiguity takes the first occurrence', () => {
    expect(zonedToUtc('2026-03-29', '02:30', 'Europe/Berlin')).toBe('2026-03-29T01:30:00Z') // 03:30 CEST
    expect(zonedToUtc('2026-10-25', '02:30', 'Europe/Berlin')).toBe('2026-10-25T00:30:00Z') // CEST occurrence
    expect(zonedToUtc('2026-10-25', '03:00', 'Europe/Berlin')).toBe('2026-10-25T02:00:00Z')
  })
  it('refuses malformed input', () => {
    expect(zonedToUtc('2026-13-01', '09:00', 'UTC')).toBeNull()
    expect(zonedToUtc('2026-12-01', '9:00', 'UTC')).toBeNull()
    expect(zonedToUtc('2026-12-01', '24:00', 'UTC')).toBeNull()
    expect(parseLocalInput('2026-12-01T09:30', 'Europe/Berlin')).toBe('2026-12-01T08:30:00Z')
    expect(parseLocalInput('garbage', 'UTC')).toBeNull()
  })
  it('week instants are local midnight to the next local midnight (23 h and 25 h days survive)', () => {
    const w = weekInstants(weekRange('2026-03-25'), 'Europe/Berlin') // week 23-29 Mar contains spring forward
    expect(w).toEqual({ from: '2026-03-22T23:00:00Z', to: '2026-03-29T22:00:00Z' })
    expect(Date.parse(w.to) - Date.parse(w.from)).toBe((7 * 24 - 1) * 3_600_000)
  })
})

describe('overlaps and activity', () => {
  const a = { starts_at: '2026-12-01T08:00:00Z', ends_at: '2026-12-01T09:00:00Z' }
  it('is half-open: back-to-back does not overlap', () => {
    expect(overlaps(a, { starts_at: '2026-12-01T09:00:00Z', ends_at: '2026-12-01T10:00:00Z' })).toBe(false)
    expect(overlaps(a, { starts_at: '2026-12-01T08:59:59Z', ends_at: '2026-12-01T10:00:00Z' })).toBe(true)
    expect(overlaps(a, { starts_at: '2026-12-01T07:00:00Z', ends_at: '2026-12-01T08:00:00Z' })).toBe(false)
    expect(overlaps(a, a)).toBe(true)
    expect(overlaps(a, { starts_at: 'x', ends_at: 'y' })).toBe(false)
  })
  it('active = confirmed or an unexpired hold', () => {
    expect(isActive(bk({}), NOW)).toBe(true)
    expect(isActive(bk({ status: 'held', hold_expires_at: '2026-12-01T00:05:00Z' }), NOW)).toBe(true)
    expect(isActive(bk({ status: 'held', hold_expires_at: '2026-11-30T23:59:00Z' }), NOW)).toBe(false)
    expect(isActive(bk({ status: 'cancelled' }), NOW)).toBe(false)
    expect(isActive(bk({ status: 'expired' }), NOW)).toBe(false)
  })
  it('flags overlapping active slot bookings but not pool bookings or cancelled ones', () => {
    const x = bk({ id: 'x' }), y = bk({ id: 'y', starts_at: '2026-12-01T08:15:00Z', ends_at: '2026-12-01T08:45:00Z' })
    expect(findOverlaps([x, y], NOW)).toHaveLength(1)
    expect(findOverlaps([x, { ...y, status: 'cancelled' }], NOW)).toHaveLength(0)
    expect(findOverlaps([{ ...x, mode: 'pool' }, { ...y, mode: 'pool' }], NOW)).toHaveLength(0)
    expect(findOverlaps([x, { ...y, resource_id: 'r2' }], NOW)).toHaveLength(0)
    expect(findOverlaps([], NOW)).toEqual([])
  })
})

describe('buildGrid', () => {
  const days = weekRange('2026-12-01').days
  const slot = (iso: string, free: boolean): Slot => ({ starts_at: iso, ends_at: new Date(Date.parse(iso) + 1_800_000).toISOString(), free })
  it('is empty without slots or bookings', () => {
    const g = buildGrid(days, [], [], 'Europe/Berlin', NOW)
    expect(g.times).toEqual([]); expect(g.cells).toEqual([])
  })
  it('places slots by LOCAL day and time and colours free / held / booked / cancelled', () => {
    const slots = [slot('2026-12-01T08:00:00Z', true), slot('2026-12-01T08:30:00Z', true), slot('2026-12-02T08:00:00Z', false), slot('2026-12-01T09:00:00Z', true)]
    const bookings = [
      bk({ id: 'h', status: 'held', hold_expires_at: '2026-12-01T00:10:00Z', starts_at: '2026-12-01T08:30:00Z', ends_at: '2026-12-01T09:00:00Z' }),
      bk({ id: 'c', status: 'cancelled', cancelled_at: '2026-11-30T10:00:00Z', starts_at: '2026-12-01T09:00:00Z', ends_at: '2026-12-01T09:30:00Z' }),
      bk({ id: 'k', status: 'confirmed', starts_at: '2026-12-03T08:00:00Z', ends_at: '2026-12-03T08:30:00Z' }),
    ]
    const g = buildGrid(days, slots, bookings, 'Europe/Berlin', NOW)
    expect(g.times).toEqual(['09:00', '09:30', '10:00'])
    const at = (t: string, d: string) => g.cells[g.times.indexOf(t)][days.indexOf(d)]
    expect(at('09:00', '2026-12-01')).toMatchObject({ state: 'free', label: 'Free', bookable: true })
    expect(at('09:30', '2026-12-01')).toMatchObject({ state: 'held', label: 'Held', bookable: false })
    expect(at('09:00', '2026-12-02')).toMatchObject({ state: 'booked', label: 'Taken', bookable: false, booking: null })
    expect(at('09:00', '2026-12-03')).toMatchObject({ state: 'booked', label: 'Booked' })
    expect(at('10:00', '2026-12-01')).toMatchObject({ state: 'cancelled', label: 'Cancelled', bookable: true })
    expect(at('10:00', '2026-12-02')).toBeNull()
  })
  it('an expired hold shows as expired and frees the cell; other-week bookings are ignored', () => {
    const b = [bk({ id: 'e', status: 'held', hold_expires_at: '2026-11-30T00:00:00Z', starts_at: '2026-12-01T08:00:00Z' }), bk({ id: 'far', starts_at: '2027-02-01T08:00:00Z' })]
    const g = buildGrid(days, [slot('2026-12-01T08:00:00Z', true)], b, 'Europe/Berlin', NOW)
    expect(g.times).toEqual(['09:00'])
    expect(g.cells[0][1]).toMatchObject({ state: 'cancelled', label: 'Expired', bookable: true })
  })
  it('a booking near local midnight lands on the right local day', () => {
    const g = buildGrid(days, [], [bk({ starts_at: '2026-12-01T23:30:00Z', ends_at: '2026-12-02T00:00:00Z' })], 'Asia/Tokyo', NOW)
    expect(g.times).toEqual(['08:30'])
    expect(g.cells[0][days.indexOf('2026-12-02')]?.state).toBe('booked')
  })
})

describe('moveFocus', () => {
  const E = [[true, false, true], [true, true, true], [false, true, false]]
  it('moves by arrows and skips gaps', () => {
    expect(moveFocus(E, 0, 0, 'ArrowRight')).toEqual([0, 2])
    expect(moveFocus(E, 0, 2, 'ArrowLeft')).toEqual([0, 0])
    expect(moveFocus(E, 0, 0, 'ArrowDown')).toEqual([1, 0])
    expect(moveFocus(E, 1, 0, 'ArrowDown')).toEqual([1, 0]) // nothing below in column 0
    expect(moveFocus(E, 0, 1 - 1, 'ArrowUp')).toEqual([0, 0])
    expect(moveFocus(E, 2, 1, 'ArrowUp')).toEqual([1, 1])
  })
  it('Home and End jump to the row ends; other keys stay', () => {
    expect(moveFocus(E, 0, 2, 'Home')).toEqual([0, 0])
    expect(moveFocus(E, 0, 0, 'End')).toEqual([0, 2])
    expect(moveFocus(E, 2, 1, 'Home')).toEqual([2, 1])
    expect(moveFocus(E, 1, 1, 'a')).toEqual([1, 1])
    expect(moveFocus([], 0, 0, 'ArrowDown')).toEqual([0, 0])
  })
})

describe('money', () => {
  it('formats fees with integer maths per currency exponent', () => {
    expect(formatFee(2500, 'EUR')).toBe('EUR 25.00')
    expect(formatFee(5, 'usd')).toBe('USD 0.05')
    expect(formatFee(500, 'JPY')).toBe('JPY 500')
    expect(formatFee(1500, 'KWD')).toBe('KWD 1.500')
    expect(formatFee(0, 'EUR')).toBe('EUR 0.00')
    expect(formatFee('9007199254740993', 'EUR')).toBe('EUR 90,071,992,547,409.93')
    expect(formatFee(1234567, null)).toBe('12,345.67')
    expect(currencyExponent('XXX')).toBe(2)
  })
  it('keeps big fee integers exact when parsing the response', () => {
    const j = parseBookingJson('{"cancel_fee_minor": 9007199254740993, "fee_currency": "EUR", "quantity": 1}') as { cancel_fee_minor: string; quantity: number }
    expect(j.cancel_fee_minor).toBe('9007199254740993')
    expect(j.quantity).toBe(1)
  })
  it('describes the fee recorded on a cancellation', () => {
    expect(cancellationNote({ cancel_fee_minor: 2500, fee_currency: 'EUR' })).toBe('Cancelled. Cancellation fee recorded: EUR 25.00.')
    expect(cancellationNote({ cancel_fee_minor: 0, fee_currency: 'EUR' })).toBe('Cancelled with no fee.')
    expect(cancellationNote({ cancel_fee_minor: '0', fee_currency: 'EUR' })).toBe('Cancelled with no fee.')
    expect(cancellationNote({ cancel_fee_minor: null, fee_currency: null })).toBe('Cancelled.')
  })
})

describe('bookingErrorMessage', () => {
  it('maps every contract error code to a human sentence', () => {
    const m = (status: number, code: string) => bookingErrorMessage(status, { code, message: 'raw', details: [] })
    expect(m(409, 'slot_taken')).toMatch(/just taken/)
    expect(m(409, 'capacity_exceeded')).toMatch(/capacity/)
    expect(m(410, 'hold_expired')).toMatch(/expired before it was confirmed/)
    expect(m(422, 'outside_availability')).toMatch(/outside the resource/)
    expect(m(409, 'invalid_transition')).toMatch(/can no longer be changed/)
    expect(m(409, 'idempotency_conflict')).toMatch(/different booking/)
    expect(m(403, 'forbidden')).toMatch(/your own/)
  })
  it('falls back on status and message', () => {
    expect(bookingErrorMessage(410, {})).toMatch(/expired before/)
    expect(bookingErrorMessage(401, null)).toMatch(/token was not accepted/)
    expect(bookingErrorMessage(403, {})).toMatch(/role may not/)
    expect(bookingErrorMessage(500, { message: 'boom' })).toBe('boom')
    expect(bookingErrorMessage(500, null)).toBe('The booking API answered 500.')
  })
})
