import axe from 'axe-core'
import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { readySession, stubSession } from '../preview/testSession'
import { click, flush, mount, q, qa, setInput, typeInto } from '../ai/testUtils'

const blocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: { getBlock: blocks.get, putBlock: blocks.put } }))
import { BookingAdminPage } from './BookingAdminPage'

const PACKS = {
  money: { currency: 'USD' },
  booking: {
    kinds: [
      { name: 'room', mode: 'slot', timezone: 'UTC', slot_minutes: 30, schedule: { mon: [{ start: '09:00', end: '12:00' }] }, capacity: 1, min_minutes: 15, max_minutes: 43200 },
      { name: 'seat', mode: 'pool', timezone: 'UTC', slot_minutes: 30, schedule: {}, capacity: 10, min_minutes: 15, max_minutes: 600 },
    ],
    hold_ttl_seconds: 600, max_horizon_days: 365, cancellation: { free_until_hours: 24, fee_minor: 2500, currency: 'USD' },
    read_roles: ['admin'], book_roles: ['admin', 'staff'], manage_roles: ['admin'], own_only: false,
  },
}
const R = (over: object) => ({ id: 'r1', kind: 'room', mode: 'slot', name: 'Room A', timezone: 'UTC', slot_minutes: 30, schedule: { mon: [{ start: '09:00', end: '12:00' }] }, capacity: 1, min_minutes: null, max_minutes: null, active: true, created_at: '2026-01-01T00:00:00Z', ...over })
const RES = [R({}), R({ id: 'r2', kind: 'seat', mode: 'pool', name: 'Desk pool', schedule: null, capacity: 10, slot_minutes: null }), R({ id: 'r3', name: 'Old room', active: false })]
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

function api(over: (m: string, url: string) => Response | undefined = () => undefined, resources: unknown[] = RES) {
  const calls: { m: string; url: string; body?: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    calls.push({ m, url, body: init.body as string | undefined })
    const o = over(m, url); if (o) return o
    if (m === 'GET' && url.includes('/booking/resources?')) return json({ items: resources, total: resources.length, limit: 200, offset: 0 })
    if (url.includes('/availability')) return json({ resource_id: 'r1', timezone: 'UTC', slot_minutes: 30, slots: [{ starts_at: '2026-01-05T09:00:00Z', ends_at: '2026-01-05T09:30:00Z', free: true }, { starts_at: '2026-01-05T09:30:00Z', ends_at: '2026-01-05T10:00:00Z', free: false }] })
    if (url.includes('/capacity')) return json({ resource_id: 'r2', capacity: 10, booked: 4, free: 6 })
    if (m === 'POST' && url.endsWith('/booking/resources')) return json({ id: 'new' }, 201)
    if (m === 'PATCH') return json({ id: 'r1' })
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const load = (f: typeof fetch) => mount(createElement(BookingAdminPage, { projectId: 'p', session: readySession(f), now: () => Date.parse('2026-01-05T10:00:00Z') }))
const val = (id: string) => (q(id) as HTMLInputElement).value

beforeEach(() => {
  blocks.get.mockReset(); blocks.put.mockReset()
  blocks.get.mockResolvedValue({ packs: structuredClone(PACKS), version: 3 })
  blocks.put.mockImplementation(async (_p: string, _n: string, body: { packs: unknown }) => ({ packs: body.packs, version: 4 }))
})

describe('BookingAdminPage resources', () => {
  it('has one h1, lists resources with status and the gate when there is no session', async () => {
    const { f } = api()
    const host = await load(f)
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(qa('bkadm-res-row')).toHaveLength(3)
    expect(qa('bkadm-res-row')[2].textContent).toContain('Disabled')
    const { f: f2 } = api()
    await mount(createElement(BookingAdminPage, { projectId: 'p', session: stubSession('no-preview') }))
    expect(q('preview-start')).not.toBeNull()
    expect(f2).not.toHaveBeenCalled()
  })
  it('shows loading, empty and error states', async () => {
    const { f } = api(() => undefined, [])
    await load(f)
    expect(q('bkadm-res-empty')).not.toBeNull()
    expect(q('bkadm-av-empty')).not.toBeNull()
    const e = api((m, u) => (m === 'GET' && u.includes('/booking/resources?') ? json({ code: 'forbidden', message: 'x', details: [] }, 403) : undefined))
    await load(e.f)
    expect(q('bkadm-res-error')?.textContent).toMatch(/manage role/)
  })
  it('filters by kind', async () => {
    const { f } = api()
    await load(f)
    await setInput(q('bkadm-filter') as HTMLSelectElement, 'seat')
    expect(qa('bkadm-res-row')).toHaveLength(1)
  })
  it('creates a pool resource with only the allowed fields', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('bkadm-create-kind') as HTMLSelectElement, 'seat')
    await setInput(q('bkadm-create-name') as HTMLInputElement, 'Floor 2')
    await setInput(q('bkadm-create-capacity') as HTMLInputElement, '25')
    await click(q('bkadm-create-submit'))
    const post = calls.find((c) => c.m === 'POST')!
    expect(post.url).toBe('http://gen.test/booking/resources')
    expect(JSON.parse(post.body!)).toEqual({ kind: 'seat', name: 'Floor 2', capacity: 25, active: true })
    expect(q('bkadm-res-notice')?.textContent).toBe('Created Floor 2.')
    expect(calls.filter((c) => c.m === 'GET' && c.url.includes('/booking/resources?')).length).toBe(2)
  })
  it('refuses a bad create client side and shows server errors by role', async () => {
    const { f, calls } = api((m) => (m === 'POST' ? json({ code: 'forbidden', message: 'x', details: [] }, 403) : undefined))
    await load(f)
    await click(q('bkadm-create-submit'))
    expect(q('bkadm-res-action-error')?.textContent).toMatch(/Name/)
    expect(calls.some((c) => c.m === 'POST')).toBe(false)
    await setInput(q('bkadm-create-name') as HTMLInputElement, 'X')
    await click(q('bkadm-create-submit'))
    expect(q('bkadm-res-action-error')?.textContent).toMatch(/manage role/)
  })
  it('edits a resource (patch of changed fields only)', async () => {
    const { f, calls } = api()
    await load(f)
    await click(qa('bkadm-res-edit')[0])
    await setInput(q('bkadm-edit-name') as HTMLInputElement, 'Room Z')
    await click(q('bkadm-edit-save'))
    const p = calls.find((c) => c.m === 'PATCH')!
    expect(p.url).toBe('http://gen.test/booking/resources/r1')
    expect(JSON.parse(p.body!)).toEqual({ name: 'Room Z' })
    expect(q('bkadm-edit-form')).toBeNull()
  })
  it('reports a no-op edit and a schedule error without calling the API', async () => {
    const { f, calls } = api()
    await load(f)
    await click(qa('bkadm-res-edit')[0])
    await click(q('bkadm-edit-save'))
    expect(q('bkadm-res-action-error')?.textContent).toBe('Nothing changed.')
    await typeInto(q('bkadm-edit-schedule') as HTMLTextAreaElement, 'mon 12:00-09:00')
    await click(q('bkadm-edit-save'))
    expect(q('bkadm-res-action-error')?.textContent).toMatch(/before the end/)
    expect(calls.some((c) => c.m === 'PATCH')).toBe(false)
  })
  it('disables after a confirmation and enables straight away', async () => {
    const { f, calls } = api()
    await load(f)
    await click(qa('bkadm-res-disable')[0])
    await click(q('bkadm-disable-no'))
    expect(q('bkadm-disable-confirm')).toBeNull()
    await click(qa('bkadm-res-disable')[0])
    await click(q('bkadm-disable-yes'))
    expect(JSON.parse(calls.find((c) => c.m === 'PATCH')!.body!)).toEqual({ active: false })
    await click(q('bkadm-res-enable'))
    expect(calls.filter((c) => c.m === 'PATCH').map((c) => JSON.parse(c.body!).active)).toEqual([false, true])
  })
})

describe('BookingAdminPage availability', () => {
  it('shows slots per day for a slot resource and rejects a long range', async () => {
    const { f, calls } = api()
    await load(f)
    await click(q('bkadm-av-check'))
    expect(calls.find((c) => c.url.includes('/availability'))!.url).toBe('http://gen.test/booking/resources/r1/availability?from=2026-01-05&to=2026-01-11&include_taken=true')
    expect(q('bkadm-av-free')?.textContent).toBe('1: 09:00')
    expect(q('bkadm-av-taken')?.textContent).toBe('1: 09:30')
    await setInput(q('bkadm-av-to') as HTMLInputElement, '2026-03-01')
    await click(q('bkadm-av-check'))
    expect(q('bkadm-av-error')?.textContent).toMatch(/31 days/)
    expect(q('bkadm-av-table')).toBeNull()
  })
  it('shows pool capacity and surfaces an availability error', async () => {
    const { f } = api()
    await load(f)
    await setInput(q('bkadm-av-resource') as HTMLSelectElement, 'r2')
    await click(q('bkadm-av-check'))
    expect(q('bkadm-av-error')?.textContent).toMatch(/start and an end/)
    await setInput(q('bkadm-av-start') as HTMLInputElement, '2026-01-06T09:00')
    await setInput(q('bkadm-av-end') as HTMLInputElement, '2026-01-06T11:00')
    await click(q('bkadm-av-check'))
    expect(q('bkadm-av-capacity')?.textContent).toBe('Capacity 10, booked 4, free 6 in that window.')
    const e = api((_m, u) => (u.includes('/capacity') ? json({ code: 'not_pool_resource', message: 'x', details: [] }, 422) : undefined))
    await load(e.f)
    await setInput(qa('bkadm-av-resource')[qa('bkadm-av-resource').length - 1] as HTMLSelectElement, 'r2')
  })
  it('lists free windows of a range resource', async () => {
    const range = [R({ id: 'g1', kind: 'court', mode: 'range', name: 'Court', schedule: null, slot_minutes: null })]
    const { f } = api((_m, u) => (u.includes('/booking/bookings?') ? json({ items: [{ id: 'b', status: 'confirmed', starts_at: '2026-01-06T10:00:00Z', ends_at: '2026-01-06T11:00:00Z' }], total: 1 }) : undefined), range)
    await load(f)
    await setInput(q('bkadm-av-start') as HTMLInputElement, '2026-01-06T09:00')
    await setInput(q('bkadm-av-end') as HTMLInputElement, '2026-01-06T12:00')
    await click(q('bkadm-av-check'))
    expect(qa('bkadm-av-gap').map((g) => g.textContent)).toEqual(['Tue 6 Jan 09:00 to Tue 6 Jan 10:00', 'Tue 6 Jan 11:00 to Tue 6 Jan 12:00'])
  })
})

describe('BookingAdminPage rules', () => {
  it('loads the rules from the packs block, with the cancellation summary', async () => {
    const { f } = api()
    await load(f)
    expect(blocks.get).toHaveBeenCalledWith('p', 'packs')
    expect(val('bkadm-book-roles')).toBe('admin, staff')
    expect(val('bkadm-fee')).toBe('2500')
    expect(q('bkadm-cancel-summary')?.textContent).toContain('USD 25.00')
    expect(qa('bkadm-kind')).toHaveLength(2)
  })
  it('saves edited rules keeping the other packs and sends expected_version', async () => {
    const { f } = api()
    await load(f)
    await setInput(q('bkadm-fee') as HTMLInputElement, '1000')
    await setInput(q('bkadm-hold-ttl') as HTMLInputElement, '300')
    await click(q('bkadm-own-only'))
    await click(q('bkadm-rules-save'))
    const [, name, body] = blocks.put.mock.calls[0]
    expect(name).toBe('packs')
    expect(body.expected_version).toBe(3)
    expect(body.packs.money).toEqual({ currency: 'USD' })
    expect(body.packs.booking.cancellation).toEqual({ free_until_hours: 24, fee_minor: 1000, currency: 'USD' })
    expect(body.packs.booking.hold_ttl_seconds).toBe(300)
    expect(body.packs.booking.own_only).toBe(true)
    expect(body.packs.booking.kinds).toHaveLength(2)
    expect(q('bkadm-rules-notice')).not.toBeNull()
    await click(q('bkadm-rules-save'))
    expect(blocks.put.mock.calls[1][2].expected_version).toBe(4)
  })
  it('blocks invalid values client side', async () => {
    const { f } = api()
    await load(f)
    await setInput(q('bkadm-fee') as HTMLInputElement, '12.5')
    await setInput(q('bkadm-manage-roles') as HTMLInputElement, '')
    await click(q('bkadm-rules-save'))
    expect(qa('bkadm-field-error').length).toBe(2)
    expect(blocks.put).not.toHaveBeenCalled()
  })
  it('adds and removes a kind and validates its fields', async () => {
    const { f } = api()
    await load(f)
    await setInput(q('bkadm-new-mode') as HTMLSelectElement, 'range')
    await click(q('bkadm-kind-add'))
    expect(qa('bkadm-kind')).toHaveLength(3)
    await click(q('bkadm-rules-save'))
    expect(qa('bkadm-field-error')[0].textContent).toMatch(/lower case/)
    await setInput(qa('bkadm-kind-name')[2] as HTMLInputElement, 'court')
    await click(q('bkadm-rules-save'))
    expect(blocks.put.mock.calls[0][2].packs.booking.kinds[2]).toMatchObject({ name: 'court', mode: 'range', min_minutes: 15 })
    await click(qa('bkadm-kind-remove')[2])
    expect(qa('bkadm-kind')).toHaveLength(2)
  })
  it('shows a 409 stale version and reloads the latest', async () => {
    blocks.put.mockRejectedValueOnce(new ApiError(409, { code: 'version_conflict', message: 'stale', details: [] }))
    const { f } = api()
    await load(f)
    await click(q('bkadm-rules-save'))
    expect(q('bkadm-rules-save-error')?.textContent).toMatch(/Someone else saved/)
    blocks.get.mockResolvedValue({ packs: structuredClone(PACKS), version: 9 })
    await click(q('bkadm-rules-reload'))
    expect(q('bkadm-rules-save-error')).toBeNull()
    await click(q('bkadm-rules-save'))
    expect(blocks.put.mock.calls[1][2].expected_version).toBe(9)
  })
  it('shows server validation issues on 422', async () => {
    blocks.put.mockRejectedValueOnce(new ApiError(422, { code: 'invalid_spec', message: 'The spec is invalid.', details: [{ path: 'packs.booking.read_roles', message: "role 'x' is not an auth role" }] }))
    const { f } = api()
    await load(f)
    await click(q('bkadm-rules-save'))
    expect(q('bkadm-rules-save-error')?.textContent).toContain('packs.booking.read_roles')
  })
  it('shows load error and the no-booking-pack state', async () => {
    blocks.get.mockRejectedValueOnce(new Error('boom'))
    const { f } = api()
    await load(f)
    expect(q('bkadm-rules-error')?.textContent).toBe('boom')
    blocks.get.mockResolvedValue({ packs: null, version: 1 })
    await load(f)
    expect(q('bkadm-rules-empty')).not.toBeNull()
  })
})

describe('BookingAdminPage a11y', () => {
  it('has no axe violations (rules, resources, edit form, availability results)', async () => {
    const { f } = api()
    const host = await load(f)
    await click(qa('bkadm-res-edit')[0])
    await click(qa('bkadm-res-disable')[0])
    await click(q('bkadm-av-check'))
    await flush()
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
