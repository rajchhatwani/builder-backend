import axe from 'axe-core'
import { act, createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { BookingsPage } from './BookingsPage'

const NOW = Date.parse('2026-12-02T10:00:00Z') // Wednesday; the week is Mon 30 Nov to Sun 6 Dec
const R1 = { id: 'r1', kind: 'practitioner', mode: 'slot', name: 'Dr A', timezone: 'Europe/Berlin', slot_minutes: 30, capacity: 1, min_minutes: null, max_minutes: null, active: true }
const POOL = { id: 'r2', kind: 'bikes', mode: 'pool', name: 'Bike pool', timezone: 'Europe/Berlin', slot_minutes: null, capacity: 3, min_minutes: null, max_minutes: null, active: true }
const slot = (iso: string, free: boolean) => ({ starts_at: iso, ends_at: new Date(Date.parse(iso) + 1_800_000).toISOString().replace('.000Z', 'Z'), free })
const SLOTS = [
  slot('2026-12-01T08:00:00Z', true), // Tue 09:00 free
  slot('2026-12-01T08:30:00Z', false), // Tue 09:30 confirmed
  slot('2026-12-02T08:00:00Z', true), // Wed 09:00 held
  slot('2026-12-03T08:00:00Z', true), // Thu 09:00 cancelled earlier
  slot('2026-12-04T08:00:00Z', true), // Fri 09:00 free
]
const bk = (o: Record<string, unknown>) => ({
  id: 'b', resource_id: 'r1', resource_name: 'Dr A', kind: 'practitioner', mode: 'slot', status: 'confirmed', starts_at: '', ends_at: '', quantity: 1, hold_expires_at: null,
  customer_ref: null, notes: null, cancel_fee_minor: null, fee_currency: null, cancelled_at: null, confirmed_at: null, ...o,
})
const BOOKINGS = [
  bk({ id: 'b1', status: 'confirmed', starts_at: '2026-12-01T08:30:00Z', ends_at: '2026-12-01T09:00:00Z', customer_ref: 'ACME' }),
  bk({ id: 'b2', status: 'held', starts_at: '2026-12-02T08:00:00Z', ends_at: '2026-12-02T08:30:00Z', hold_expires_at: '2026-12-02T10:10:00Z' }),
  bk({ id: 'b3', status: 'cancelled', starts_at: '2026-12-03T08:00:00Z', ends_at: '2026-12-03T08:30:00Z', cancelled_at: '2026-12-01T00:00:00Z', cancel_fee_minor: 2500, fee_currency: 'EUR' }),
]
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const err = (status: number, code: string) => json({ code, message: 'raw', details: [] }, status)

function api(over: (m: string, url: string, body: unknown) => Response | undefined = () => undefined, resources: unknown[] = [R1]) {
  const calls: { m: string; url: string; body: Record<string, unknown> | null; auth?: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    const body = init.body ? JSON.parse(init.body as string) : null
    calls.push({ m, url, body, auth: (init.headers as Record<string, string>).Authorization })
    const o = over(m, url, body)
    if (o) return o
    if (url.includes('/availability')) return json({ resource_id: 'r1', timezone: 'Europe/Berlin', slot_minutes: 30, slots: url.includes('from=2026-11-30') ? SLOTS : [] })
    if (url.includes('/capacity')) return json({ resource_id: 'r2', capacity: 3, booked: 1, free: 2 })
    if (m === 'GET' && url.includes('/booking/resources')) return json({ items: resources, total: resources.length, limit: 200, offset: 0 })
    if (m === 'GET' && url.includes('/booking/bookings')) return json({ items: url.includes('from=2026-11-29') ? BOOKINGS : [], total: 3, limit: 200, offset: 0 })
    if (m === 'POST' && url.endsWith('/booking/bookings')) return json(bk({ id: 'new', status: 'held', starts_at: body?.starts_at, ends_at: body?.ends_at, hold_expires_at: '2026-12-02T10:15:00Z' }), 201)
    if (url.endsWith('/confirm')) return json(bk({ id: 'b2', status: 'confirmed', starts_at: '2026-12-02T08:00:00Z' }))
    if (url.endsWith('/cancel')) return json(bk({ id: 'b1', status: 'cancelled', starts_at: '2026-12-01T08:30:00Z', cancel_fee_minor: 2500, fee_currency: 'EUR' }))
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const el = (f: typeof fetch) => createElement(BookingsPage, { projectId: 'p', session: readySession(f), now: () => NOW })
async function load(f: typeof fetch) {
  const host = await mount(el(f))
  await flush()
  return host
}
const cell = (key: string) => qa('bookings-cell').find((c) => c.dataset.key === key)!
const TUE9 = '2026-12-01|09:00', TUE930 = '2026-12-01|09:30', WED9 = '2026-12-02|09:00', THU9 = '2026-12-03|09:00'
const key = async (el: Element, k: string) => { await act(async () => { el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true })) }); await flush() }

describe('BookingsPage', () => {
  it('explains when no preview origin is configured and fetches nothing', async () => {
    const { f } = api()
    await mount(createElement(BookingsPage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('bookings-no-origin')).not.toBeNull()
    expect(f).not.toHaveBeenCalled()
  })

  it('loads resources, availability (with taken slots) and the week of bookings straight away and shows no token or password input', async () => {
    const { f, calls } = api()
    const host = await mount(el(f))
    expect(host.querySelector('input[type=password]')).toBeNull()
    expect(host.textContent ?? '').not.toMatch(/bearer|paste a/i)
    expect(host.querySelector('[data-testid$="-token"],[data-testid$="-notoken"],[data-testid$="bookings-load"]')).toBeNull()
    expect(calls.every((c) => c.url.startsWith('http://gen.test/booking/'))).toBe(true)
    expect(calls.find((c) => c.url.includes('/availability'))!.url).toContain('/booking/resources/r1/availability?from=2026-11-30&to=2026-12-06&include_taken=true')
    const bu = calls.find((c) => c.m === 'GET' && c.url.includes('/booking/bookings'))!.url
    expect(bu).toContain('resource_id=r1')
    expect(decodeURIComponent(bu)).toContain('from=2026-11-29T23:00:00Z&to=2026-12-06T23:00:00Z')
    expect(q('bookings-week-label')?.textContent).toBe('Mon 30 Nov to Sun 6 Dec')
    expect(q('bookings-tz')?.textContent).toMatch(/Europe\/Berlin/)
  })

  it('draws the week grid in resource-local time with free / held / booked / cancelled colours', async () => {
    const { f } = api()
    await load(f)
    expect(qa('bookings-day').map((d) => d.textContent)).toEqual(['Mon 30 Nov', 'Tue 1 Dec', 'Wed 2 Dec', 'Thu 3 Dec', 'Fri 4 Dec', 'Sat 5 Dec', 'Sun 6 Dec'])
    expect(qa('bookings-row')).toHaveLength(2)
    expect(qa('bookings-row')[0].querySelector('th')?.textContent).toBe('09:00')
    expect(cell(TUE9).dataset.state).toBe('free')
    expect(cell(TUE930).dataset.state).toBe('booked')
    expect(cell(WED9).dataset.state).toBe('held')
    expect(cell(THU9).dataset.state).toBe('cancelled')
    expect(cell(TUE9).getAttribute('aria-label')).toBe('Tue 1 Dec 09:00, Free')
    expect(cell(WED9).getAttribute('aria-label')).toBe('Wed 2 Dec 09:00, Held')
    expect(qa('bookings-cell')).toHaveLength(5)
  })

  it('create hold: posts the slot with an idempotency key and shows the hold deadline', async () => {
    const { f, calls } = api()
    await load(f)
    await click(cell(TUE9))
    expect(q('bookings-selected')).not.toBeNull()
    await setInput(q('bookings-customer') as HTMLInputElement, 'ACME')
    await click(q('bookings-hold'))
    const post = calls.find((c) => c.m === 'POST')!
    expect(post.url).toBe('http://gen.test/booking/bookings')
    expect(post.body).toMatchObject({ resource_id: 'r1', starts_at: '2026-12-01T08:00:00Z', ends_at: '2026-12-01T08:30:00Z', confirm: false, customer_ref: 'ACME' })
    expect(String(post.body!.idempotency_key).length).toBeGreaterThan(8)
    expect(q('bookings-notice')?.textContent).toBe('Hold created for Tue 1 Dec 09:00; confirm before Wed 2 Dec 11:15.')
    expect(calls.filter((c) => c.url.includes('/availability')).length).toBeGreaterThan(1) // reloaded after the write
  })

  it('F-0636: a refresh or action keeps the grid mounted (focus and selection survive)', async () => {
    const { f } = api()
    await load(f)
    const grid = q('bookings-grid')!
    const c = cell(WED9)
    await click(c)
    ;(c as HTMLElement).focus()
    await click(q('bookings-refresh'))
    expect(grid.isConnected).toBe(true)
    expect(cell(WED9)).toBe(c)
    expect(document.activeElement).toBe(c)
    expect(q('bookings-booking-info')).not.toBeNull()
    await click(q('bookings-confirm'))
    expect(grid.isConnected).toBe(true)
  })
  it('confirm a held slot', async () => {
    const { f, calls } = api()
    await load(f)
    await click(cell(WED9))
    expect(q('bookings-booking-info')?.textContent).toMatch(/hold expires Wed 2 Dec 11:10/)
    await click(q('bookings-confirm'))
    expect(calls.find((c) => c.m === 'POST')!.url).toBe('http://gen.test/booking/bookings/b2/confirm')
    expect(q('bookings-notice')?.textContent).toBe('Booking confirmed for Wed 2 Dec 09:00.')
  })

  it('cancel a confirmed booking: asks first, explains the fee, then shows the recorded fee with integer maths', async () => {
    const { f, calls } = api()
    await load(f)
    await click(cell(TUE930))
    expect(q('bookings-cancel-confirm')).toBeNull()
    await click(q('bookings-cancel-btn'))
    expect(q('bookings-cancel-confirm')?.textContent).toMatch(/may cost the cancellation fee/)
    await click(q('bookings-cancel-no'))
    expect(q('bookings-cancel-confirm')).toBeNull()
    await click(q('bookings-cancel-btn'))
    await setInput(q('bookings-reason') as HTMLInputElement, 'customer called')
    await click(q('bookings-cancel-yes'))
    const post = calls.find((c) => c.m === 'POST')!
    expect(post.url).toBe('http://gen.test/booking/bookings/b1/cancel')
    expect(post.body).toEqual({ reason: 'customer called' })
    expect(q('bookings-notice')?.textContent).toBe('Cancelled. Cancellation fee recorded: EUR 25.00.')
  })

  it('cancelling a hold says it is free; a zero fee reads as no fee', async () => {
    const { f } = api((_m, u) => (u.endsWith('/cancel') ? json(bk({ id: 'b2', status: 'cancelled', cancel_fee_minor: 0, fee_currency: 'EUR' })) : undefined))
    await load(f)
    await click(cell(WED9))
    await click(q('bookings-cancel-btn'))
    expect(q('bookings-cancel-confirm')?.textContent).toMatch(/Cancelling a hold is free/)
    await click(q('bookings-cancel-yes'))
    expect(q('bookings-notice')?.textContent).toBe('Cancelled with no fee.')
  })

  it('shows the recorded fee of an earlier cancellation and still allows a new hold', async () => {
    const { f } = api()
    await load(f)
    await click(cell(THU9))
    expect(q('bookings-booking-info')?.textContent).toMatch(/Cancelled\. Cancellation fee recorded: EUR 25\.00\./)
    expect(q('bookings-hold')).not.toBeNull()
  })

  it('does not offer a hold on a taken slot', async () => {
    const { f } = api((m, u) => (u.includes('/booking/bookings') && m === 'GET' ? json({ items: [], total: 0, limit: 200, offset: 0 }) : undefined))
    await load(f)
    await click(cell(TUE930))
    expect(q('bookings-taken')).not.toBeNull()
    expect(q('bookings-hold')).toBeNull()
  })

  it.each([
    ['slot_taken', 409, /just taken/],
    ['capacity_exceeded', 409, /capacity/],
    ['outside_availability', 422, /outside the resource/],
    ['invalid_transition', 409, /can no longer be changed/],
  ])('maps the hold error %s to a human message and reloads', async (code, status, re) => {
    const { f, calls } = api((m, u) => (m === 'POST' && u.endsWith('/booking/bookings') ? err(status, code) : undefined))
    await load(f)
    await click(cell(TUE9))
    const before = calls.filter((c) => c.url.includes('/availability')).length
    await click(q('bookings-hold'))
    expect(q('bookings-error')?.textContent).toMatch(re)
    expect(calls.filter((c) => c.url.includes('/availability')).length).toBeGreaterThan(before)
  })

  it('maps hold_expired (410) on confirm and invalid_transition on cancel', async () => {
    const a = api((_m, u) => (u.endsWith('/confirm') ? err(410, 'hold_expired') : undefined))
    await load(a.f)
    await click(cell(WED9))
    await click(q('bookings-confirm'))
    expect(q('bookings-error')?.textContent).toMatch(/hold expired before it was confirmed/)
    const b = api((_m, u) => (u.endsWith('/cancel') ? err(409, 'invalid_transition') : undefined))
    await load(b.f)
    await click(cell(TUE930))
    await click(q('bookings-cancel-btn'))
    await click(q('bookings-cancel-yes'))
    expect(q('bookings-error')?.textContent).toMatch(/can no longer be changed/)
  })

  it('keeps the same idempotency key on a retry after an error and uses a fresh one after success', async () => {
    let n = 0
    const { f, calls } = api((m, u) => (m === 'POST' && u.endsWith('/booking/bookings') && n++ === 0 ? err(409, 'slot_taken') : undefined))
    await load(f)
    await click(cell(TUE9))
    await click(q('bookings-hold'))
    await click(q('bookings-hold'))
    const posts = calls.filter((c) => c.m === 'POST')
    expect(posts[0].body!.idempotency_key).toBe(posts[1].body!.idempotency_key)
    expect(q('bookings-notice')?.textContent).toMatch(/Hold created/)
  })

  it('moves focus between cells with the arrow keys (roving tabindex), skipping empty cells', async () => {
    const { f } = api()
    await load(f)
    const pos = (p: string) => qa('bookings-cell').find((c) => c.dataset.pos === p)!
    expect(qa('bookings-cell').filter((c) => c.tabIndex === 0)).toHaveLength(1)
    pos('0:1').focus()
    await flush()
    await key(pos('0:1'), 'ArrowRight')
    expect(document.activeElement).toBe(pos('0:2'))
    await key(pos('0:2'), 'ArrowRight')
    expect(document.activeElement).toBe(pos('0:3'))
    await key(pos('0:3'), 'ArrowLeft')
    await key(pos('0:2'), 'ArrowLeft')
    expect(document.activeElement).toBe(pos('0:1'))
    await key(pos('0:1'), 'ArrowDown')
    expect(document.activeElement).toBe(pos('1:1'))
    await key(pos('1:1'), 'ArrowUp')
    expect(document.activeElement).toBe(pos('0:1'))
    await key(pos('0:1'), 'End')
    expect(document.activeElement).toBe(pos('0:4'))
    await key(pos('0:4'), 'Home')
    expect(document.activeElement).toBe(pos('0:1'))
    expect(pos('0:1').tabIndex).toBe(0)
    expect(pos('0:2').tabIndex).toBe(-1)
  })

  it('navigates weeks and shows the empty state for a week without slots', async () => {
    const { f, calls } = api()
    await load(f)
    await click(q('bookings-next'))
    expect(q('bookings-week-label')?.textContent).toBe('Mon 7 Dec to Sun 13 Dec')
    expect(calls.filter((c) => c.url.includes('/availability')).pop()!.url).toContain('from=2026-12-07&to=2026-12-13')
    expect(q('bookings-grid-empty')).not.toBeNull()
    expect(q('bookings-grid')).toBeNull()
    await click(q('bookings-prev'))
    await click(q('bookings-prev'))
    expect(q('bookings-week-label')?.textContent).toBe('Mon 23 Nov to Sun 29 Nov')
    await click(q('bookings-today'))
    expect(q('bookings-week-label')?.textContent).toBe('Mon 30 Nov to Sun 6 Dec')
    expect(q('bookings-grid')).not.toBeNull()
  })

  it('shows empty resources, a loading state and API errors', async () => {
    const e = api(undefined, [])
    await load(e.f)
    expect(q('bookings-resources-empty')).not.toBeNull()
    const a = api((_m, u) => (u.includes('/availability') ? err(500, 'boom') : undefined))
    await load(a.f)
    expect(q('bookings-grid-error')?.textContent).toMatch(/answered 500|raw/)
    const d = api((_m, u) => (u.includes('/booking/resources') && !u.includes('/availability') ? err(403, 'forbidden') : undefined))
    await load(d.f)
    expect(q('bookings-resources-error')?.textContent).toMatch(/own bookings|role may not/)
    let release: (r: Response) => void = () => undefined
    const slow = api((_m, u) => (u.includes('/availability') ? (new Promise<Response>((r) => { release = r }) as unknown as Response) : undefined))
    await load(slow.f)
    expect(q('bookings-loading')).not.toBeNull()
    await act(async () => { release(json({ slots: [] })) })
    await flush()
    expect(q('bookings-loading')).toBeNull()
  })

  it('pool resource: checks capacity and holds a quantity for a local time range converted to UTC', async () => {
    const { f, calls } = api(undefined, [POOL])
    await load(f)
    expect(q('bookings-range-form')).not.toBeNull()
    expect(calls.some((c) => c.url.includes('/availability'))).toBe(false)
    await setInput(q('bookings-start') as HTMLInputElement, '2026-12-03T10:00')
    await setInput(q('bookings-end') as HTMLInputElement, '2026-12-03T12:00')
    await setInput(q('bookings-qty') as HTMLInputElement, '2')
    await click(q('bookings-capacity'))
    expect(decodeURIComponent(calls.find((c) => c.url.includes('/capacity'))!.url)).toContain('starts_at=2026-12-03T09:00:00Z&ends_at=2026-12-03T11:00:00Z')
    expect(q('bookings-capacity-result')?.textContent).toBe('Capacity 3, booked 1, free 2 in that window.')
    await click(q('bookings-range-hold'))
    expect(calls.find((c) => c.m === 'POST')!.body).toMatchObject({ resource_id: 'r2', starts_at: '2026-12-03T09:00:00Z', ends_at: '2026-12-03T11:00:00Z', quantity: 2, confirm: false })
  })

  it('pool form refuses an end before the start', async () => {
    const { f } = api(undefined, [POOL])
    await load(f)
    await setInput(q('bookings-start') as HTMLInputElement, '2026-12-03T12:00')
    await setInput(q('bookings-end') as HTMLInputElement, '2026-12-03T10:00')
    expect((q('bookings-range-hold') as HTMLButtonElement).disabled).toBe(true)
  })

  it('F-1288: a pool cell with two bookings in the same start slot lists and acts on each of them', async () => {
    const pool = (o: Record<string, unknown>) => bk({ resource_id: 'r2', resource_name: 'Bike pool', kind: 'bikes', mode: 'pool', starts_at: '2026-12-02T09:00:00Z', ends_at: '2026-12-02T11:00:00Z', ...o })
    const two = [pool({ id: 'pa', status: 'confirmed', customer_ref: 'ANNA' }), pool({ id: 'pb', status: 'held', customer_ref: 'ZED', hold_expires_at: '2026-12-02T10:10:00Z' })]
    const { f, calls } = api((m, url) => (m === 'GET' && url.includes('/booking/bookings?') ? json({ items: two, total: 2, limit: 200, offset: 0 }) : undefined), [POOL])
    await load(f)
    await click(cell('2026-12-02|10:00'))
    const infos = qa('bookings-booking-info').map((e) => e.textContent)
    expect(infos).toHaveLength(2)
    expect(infos.join(' ')).toContain('ANNA'); expect(infos.join(' ')).toContain('ZED')
    await click(q('bookings-confirm'))
    expect(calls.some((c) => c.m === 'POST' && c.url.endsWith('/booking/bookings/pb/confirm'))).toBe(true)
    expect(qa('bookings-cancel-btn')).toHaveLength(2)
    await click(qa('bookings-cancel-btn')[1])
    await click(q('bookings-cancel-yes'))
    expect(calls.some((c) => c.m === 'POST' && c.url.endsWith('/booking/bookings/pb/cancel'))).toBe(true)
  })

  it('F-1291: customer, notes and reason are cleared when another cell is chosen and after a successful action', async () => {
    const { f } = api()
    await load(f)
    await click(cell(TUE9))
    await setInput(q('bookings-customer') as HTMLInputElement, 'Anna')
    await setInput(q('bookings-notes') as HTMLInputElement, 'allergy')
    await click(cell('2026-12-04|09:00'))
    expect((q('bookings-customer') as HTMLInputElement).value).toBe('')
    expect((q('bookings-notes') as HTMLInputElement).value).toBe('')
    await setInput(q('bookings-customer') as HTMLInputElement, 'Bob')
    await click(q('bookings-hold'))
    expect((q('bookings-customer') as HTMLInputElement).value).toBe('')
    await click(cell(TUE930))
    await click(q('bookings-cancel-btn'))
    await setInput(q('bookings-reason') as HTMLInputElement, 'sick')
    await click(cell(WED9))
    await click(q('bookings-cancel-btn'))
    expect((q('bookings-reason') as HTMLInputElement).value).toBe('')
  })

  it('F-1292: warns when the booking or resource list is capped below its total', async () => {
    const { f } = api((m, url) => {
      if (m !== 'GET') return undefined
      if (url.includes('/booking/bookings?')) return json({ items: url.includes('from=2026-11-29') ? BOOKINGS : [], total: 250, limit: 200, offset: 0 })
      if (url.includes('/booking/resources?')) return json({ items: [R1], total: 300, limit: 200, offset: 0 })
      return undefined
    })
    await load(f)
    expect(q('bookings-truncated')).not.toBeNull()
    expect(q('bookings-resources-truncated')).not.toBeNull()
  })

  it('has no axe violations (grid, selection, cancel confirm, range form)', async () => {
    const { f } = api()
    const host = await load(f)
    await click(cell(TUE930))
    await click(q('bookings-cancel-btn'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
    const p = api(undefined, [POOL])
    const host2 = await load(p.f)
    const res2 = await axe.run(host2, { rules: { 'color-contrast': { enabled: false } } })
    expect(res2.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
