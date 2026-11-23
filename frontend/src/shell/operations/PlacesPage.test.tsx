import axe from 'axe-core'
import { act, createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { PlacesPage } from './PlacesPage'
import { empty, fakeApi, json } from './opsTestKit'

const NOW = Date.parse('2026-01-01T12:00:00Z')
const PLACE = { id: 'pl1', name: 'HQ', kind: 'office', lat_micro: 40_500_000, lng_micro: -74_000_000, lat: '40.500000', lng: '-74.000000', created_at: '2026-01-01T00:00:00Z' }
const CIRCLE = { id: 'g1', name: 'Depot', shape: 'circle', center: { lat_micro: 40_000_000, lng_micro: -74_000_000 }, radius_m: 500, vertices: null }
const POLY = { id: 'g2', name: 'North', shape: 'polygon', center: null, radius_m: null, vertices: [{ lat_micro: 1_000_000, lng_micro: 1_000_000 }, { lat_micro: 1_000_000, lng_micro: 2_000_000 }, { lat_micro: 2_000_000, lng_micro: 2_000_000 }] }
const EVENT = { id: 'e1', subject_id: 'van-1', geofence_id: 'g1', geofence_name: 'Depot', event: 'enter', lat_micro: 1, lng_micro: 2, occurred_at: '2026-01-01T11:00:00Z' }
const POS = { subject_id: 'van-1', subject_kind: 'courier', lat_micro: 40_000_000, lng_micro: -74_000_000, lat: '40.000000', lng: '-74.000000', seq: 3, recorded_at: '2026-01-01T11:59:00Z', updated_at: '2026-01-01T11:59:30Z' }

const base = (over: Parameters<typeof fakeApi>[0] = () => undefined) => fakeApi(over, (m, url) => {
  if (m !== 'GET') return json({}, 404)
  if (url.includes('/geo/places/')) return json({ items: [{ ...PLACE, distance_m: 120 }], truncated: false })
  if (url.includes('/geo/places')) return json({ items: [PLACE], total: 1, limit: 100, offset: 0 })
  if (url.includes('/geo/geofences')) return json({ items: [CIRCLE, POLY], total: 2, limit: 100, offset: 0 })
  if (url.includes('/geo/events')) return json({ items: [EVENT], total: 1, limit: 50, offset: 0 })
  if (url.includes('/history')) return json({ items: [{ subject_id: 'van-1', seq: 3, recorded_at: '2026-01-01T11:59:00Z', lat: '40.000000', lng: '-74.000000' }], retention_cap: 100 })
  if (url.includes('/location/positions')) return json({ items: [POS], truncated: false })
  return json({}, 404)
})
const load = (f: typeof fetch) => mount(createElement(PlacesPage, { projectId: 'p', session: readySession(f), now: () => NOW }))
const typeChars = async (el: HTMLInputElement, text: string) => {
  for (let i = 1; i <= text.length; i++) {
    await setInput(el, text.slice(0, i))
    expect(el.value).toBe(text.slice(0, i))
  }
}

describe('PlacesPage', () => {
  it('gates without a session and has one h1', async () => {
    const { f } = base()
    const host = await mount(createElement(PlacesPage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('places-page-no-origin')).not.toBeNull()
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(f).not.toHaveBeenCalled()
  })

  it('lists places, geofences, events and positions with exactly one h1 and no skipped heading level', async () => {
    const { f } = base()
    const host = await load(f)
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(qa('place-row')).toHaveLength(1)
    expect(qa('place-row')[0].textContent).toContain('40.500000')
    expect(qa('fence-row').map((r) => r.textContent)).toEqual([expect.stringContaining('radius 500 m'), expect.stringContaining('3 vertices')])
    expect(qa('event-row')[0].textContent).toContain('enter')
    expect(qa('position-row')[0].textContent).toContain('30s ago')
    expect(host.querySelector('section[aria-labelledby]')).toBeNull()
    const levels = [...host.querySelectorAll('h1,h2,h3')].map((h) => Number(h.tagName[1]))
    levels.forEach((l, i) => { if (i > 0) expect(l - levels[i - 1]).toBeLessThanOrEqual(1) })
  })

  it('shows loading, empty and error states per section, and the 403 as a clear message', async () => {
    const { f } = base((_m, u) => (u.includes('/geo/places?') ? json({ code: 'forbidden', message: 'x' }, 403) : u.includes('/geo/geofences') ? json({ items: [], total: 0 }) : u.includes('/location') ? json({ detail: 'Not Found' }, 404) : undefined))
    await load(f)
    expect(q('places-error')?.textContent).toMatch(/403.*role/)
    expect(q('fences-empty')).not.toBeNull()
    expect(q('positions-error')?.textContent).toMatch(/no location API/)
    expect(qa('event-row')).toHaveLength(1)
  })

  it('filters places by kind', async () => {
    const { f, calls } = base()
    await load(f)
    await setInput(q('place-filter-kind') as HTMLInputElement, 'shop')
    await click(q('place-filter-apply'))
    expect(calls.some((c) => c.url.includes('/geo/places?') && c.url.includes('kind=shop'))).toBe(true)
  })

  it('ignores a slow answer for an old filter (stale-fetch guard)', async () => {
    let release: (r: Response) => void = () => {}
    const slow = new Promise<Response>((res) => { release = res })
    const { f } = base((_m, u) => (u.includes('/geo/places?') && u.includes('kind=old') ? slow : u.includes('/geo/places?') && u.includes('kind=new') ? json({ items: [{ ...PLACE, id: 'n', name: 'Newer' }], total: 1 }) : undefined))
    await load(f)
    await setInput(q('place-filter-kind') as HTMLInputElement, 'old')
    await click(q('place-filter-apply'))
    await setInput(q('place-filter-kind') as HTMLInputElement, 'new')
    await click(q('place-filter-apply'))
    await act(async () => { release(json({ items: [{ ...PLACE, id: 'o', name: 'Older' }], total: 1 })) })
    await flush()
    expect(qa('place-row').map((r) => r.textContent).join('')).toContain('Newer')
    expect(qa('place-row').map((r) => r.textContent).join('')).not.toContain('Older')
  })

  it('creates a place from degrees typed char by char, sending integer micro-degrees; a double click posts once', async () => {
    const { f, to } = base((m, u) => (m === 'POST' && u.endsWith('/geo/places') ? json(PLACE, 201) : undefined))
    await load(f)
    await setInput(q('place-name') as HTMLInputElement, 'Cafe')
    await typeChars(q('place-point-lat') as HTMLInputElement, '-0.5')
    await typeChars(q('place-point-lng') as HTMLInputElement, '-74.123456')
    await act(async () => { q('place-save')!.click(); q('place-save')!.click() })
    await flush()
    expect(to('POST', '/geo/places')).toHaveLength(1)
    expect(to('POST', '/geo/places')[0].body).toEqual({ name: 'Cafe', kind: null, lat_micro: -500_000, lng_micro: -74_123_456 })
    expect(q('place-save-ok')?.textContent).toBe('Place created.')
    expect((q('place-name') as HTMLInputElement).value).toBe('')
  })

  it('refuses a bad coordinate locally and shows the API error for a refused create', async () => {
    const { f, to } = base((m) => (m === 'POST' ? json({ code: 'invalid_coordinates', message: 'x' }, 422) : undefined))
    await load(f)
    await setInput(q('place-name') as HTMLInputElement, 'Cafe')
    await typeChars(q('place-point-lat') as HTMLInputElement, '91')
    await typeChars(q('place-point-lng') as HTMLInputElement, '10')
    await click(q('place-save'))
    expect(q('place-save-error')?.textContent).toMatch(/Latitude/)
    expect(to('POST', '/geo/places')).toHaveLength(0)
    await typeChars(q('place-point-lat') as HTMLInputElement, '9')
    await click(q('place-save'))
    expect(q('place-save-error')?.textContent).toMatch(/-90 to 90/)
  })

  it('edits a place with PUT /geo/places/{id}', async () => {
    const { f, to } = base((m) => (m === 'PUT' ? json({ ...PLACE, name: 'HQ2' }) : undefined))
    await load(f)
    await click(qa('place-edit')[0])
    expect((q('place-name') as HTMLInputElement).value).toBe('HQ')
    expect((q('place-point-lat') as HTMLInputElement).value).toBe('40.5')
    await setInput(q('place-name') as HTMLInputElement, 'HQ2')
    await click(q('place-save'))
    const put = to('PUT', '/geo/places/pl1')
    expect(put).toHaveLength(1)
    expect(put[0].body).toEqual({ name: 'HQ2', kind: 'office', lat_micro: 40_500_000, lng_micro: -74_000_000 })
    expect(q('place-save-ok')?.textContent).toBe('Place updated.')
  })

  it('asks before deleting a place and can be cancelled', async () => {
    const { f, to } = base((m) => (m === 'DELETE' ? empty() : undefined))
    await load(f)
    await click(qa('place-delete')[0])
    expect(q('place-confirm')?.textContent).toMatch(/Delete the place HQ/)
    expect(to('DELETE', '/geo/places/pl1')).toHaveLength(0)
    await click(q('place-confirm')!.querySelectorAll('button')[1])
    expect(q('place-confirm')).toBeNull()
    await click(qa('place-delete')[0])
    await click(q('place-confirm-yes'))
    expect(to('DELETE', '/geo/places/pl1')).toHaveLength(1)
    expect(q('place-del-ok')?.textContent).toBe('Deleted HQ.')
  })

  it('shows a delete refusal (403) instead of failing silently', async () => {
    const { f } = base((m) => (m === 'DELETE' ? json({ code: 'forbidden', message: 'no' }, 403) : undefined))
    await load(f)
    await click(qa('place-delete')[0])
    await click(q('place-confirm-yes'))
    expect(q('place-del-error')?.textContent).toMatch(/write roles/)
  })

  it('runs nearest and within queries', async () => {
    const { f, calls } = base()
    await load(f)
    await typeChars(q('query-point-lat') as HTMLInputElement, '40.5')
    await typeChars(q('query-point-lng') as HTMLInputElement, '-74')
    await click(q('query-run'))
    expect(calls.some((c) => c.url.includes('/geo/places/nearest?lat_micro=40500000&lng_micro=-74000000&n=5'))).toBe(true)
    expect(qa('query-row')[0].textContent).toContain('120')
    await setInput(q('query-mode') as HTMLSelectElement, 'within')
    await setInput(q('query-radius') as HTMLInputElement, '2500')
    await click(q('query-run'))
    expect(calls.some((c) => c.url.includes('/geo/places/within?') && c.url.includes('radius_m=2500'))).toBe(true)
  })

  it('creates a circle geofence', async () => {
    const { f, to } = base((m, u) => (m === 'POST' && u.endsWith('/geo/geofences') ? json(CIRCLE, 201) : undefined))
    await load(f)
    await setInput(q('fence-name') as HTMLInputElement, 'Yard')
    await typeChars(q('fence-center-lat') as HTMLInputElement, '40.25')
    await typeChars(q('fence-center-lng') as HTMLInputElement, '-74.5')
    await typeChars(q('fence-radius') as HTMLInputElement, '750')
    await click(q('fence-save'))
    expect(to('POST', '/geo/geofences')[0].body).toEqual({ name: 'Yard', shape: 'circle', center: { lat_micro: 40_250_000, lng_micro: -74_500_000 }, radius_m: 750 })
  })

  it('creates a polygon with the vertices editor (add, remove, minimum of three)', async () => {
    const { f, to } = base((m, u) => (m === 'POST' && u.endsWith('/geo/geofences') ? json(POLY, 201) : undefined))
    await load(f)
    await setInput(q('fence-name') as HTMLInputElement, 'Zone')
    await setInput(q('fence-shape') as HTMLSelectElement, 'polygon')
    expect(qa('vertex-row')).toHaveLength(3)
    const pts = [['1', '1'], ['1', '2'], ['2', '2']]
    for (const [i, [la, ln]] of pts.entries()) {
      await typeChars(qa('vertex-lat')[i] as HTMLInputElement, la)
      await typeChars(qa('vertex-lng')[i] as HTMLInputElement, ln)
    }
    await click(qa('vertex-remove')[2])
    expect(qa('vertex-row')).toHaveLength(2)
    await click(q('fence-save'))
    expect(q('fence-save-error')?.textContent).toMatch(/at least 3/)
    expect(to('POST', '/geo/geofences')).toHaveLength(0)
    await click(q('vertex-add'))
    await typeChars(qa('vertex-lat')[2] as HTMLInputElement, '2')
    await typeChars(qa('vertex-lng')[2] as HTMLInputElement, '2')
    await click(q('fence-save'))
    expect(to('POST', '/geo/geofences')[0].body).toEqual({
      name: 'Zone', shape: 'polygon',
      vertices: [{ lat_micro: 1_000_000, lng_micro: 1_000_000 }, { lat_micro: 1_000_000, lng_micro: 2_000_000 }, { lat_micro: 2_000_000, lng_micro: 2_000_000 }],
    })
  })

  it('edits a geofence with PUT /geo/geofences/{id}', async () => {
    const { f, to } = base((m) => (m === 'PUT' ? json(POLY) : undefined))
    await load(f)
    await click(qa('fence-edit')[1])
    expect((q('fence-shape') as HTMLSelectElement).value).toBe('polygon')
    expect(qa('vertex-row')).toHaveLength(3)
    await setInput(q('fence-name') as HTMLInputElement, 'North 2')
    await click(q('fence-save'))
    const put = to('PUT', '/geo/geofences/g2')
    expect(put).toHaveLength(1)
    expect(put[0].body).toMatchObject({ name: 'North 2', shape: 'polygon' })
    expect((put[0].body as { vertices: unknown[] }).vertices).toHaveLength(3)
    expect(q('fence-save-ok')?.textContent).toBe('Geofence updated.')
  })

  it('asks before deleting a geofence', async () => {
    const { f, to } = base((m) => (m === 'DELETE' ? empty() : undefined))
    await load(f)
    await click(qa('fence-delete')[0])
    expect(to('DELETE', '/geo/geofences/g1')).toHaveLength(0)
    await click(q('fence-confirm-yes'))
    expect(to('DELETE', '/geo/geofences/g1')).toHaveLength(1)
  })

  it('checks which geofences contain a point', async () => {
    const { f, to } = base((_m, u) => (u.endsWith('/geo/contains') ? json({ items: [CIRCLE] }) : undefined))
    await load(f)
    await typeChars(q('contains-point-lat') as HTMLInputElement, '40')
    await typeChars(q('contains-point-lng') as HTMLInputElement, '-74')
    await click(q('contains-run'))
    expect(to('POST', '/geo/contains')[0].body).toEqual({ point: { lat_micro: 40_000_000, lng_micro: -74_000_000 } })
    expect(q('contains-result')?.textContent).toBe('Inside: Depot')
  })

  it('shows the position history of a subject', async () => {
    const { f } = base()
    await load(f)
    await click(qa('position-history')[0])
    expect(q('history-panel')?.querySelector('h3')?.textContent).toBe('History of van-1')
    expect(qa('history-row')[0].textContent).toContain('#3')
  })

  it('has no axe violations (forms, tables, editing a polygon)', async () => {
    const { f } = base()
    const host = await load(f)
    await click(qa('fence-edit')[1])
    await click(qa('place-delete')[0])
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
