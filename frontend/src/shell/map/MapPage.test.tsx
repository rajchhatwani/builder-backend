import axe from 'axe-core'
import { createElement } from 'react'
import { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { MapPage } from './MapPage'

const NOW = Date.parse('2026-01-01T12:00:00Z')
const iso = (agoS: number) => new Date(NOW - agoS * 1000).toISOString()
const pos = (id: string, kind: string | null, lat: number, lng: number, ago: number) => ({
  subject_id: id, subject_kind: kind, lat_micro: lat, lng_micro: lng, lat: '', lng: '', seq: 1, recorded_at: iso(ago), updated_at: iso(ago),
})
const POS = [
  pos('van-1', 'courier', 40_000_000, -74_000_000, 10),
  pos('van-2', 'courier', 40_005_000, -73_995_000, 20),
  pos('van-3', 'courier', 41_000_000, -73_000_000, 400),
]
const FENCES = [
  { id: 'g1', name: 'Depot', shape: 'circle', center: { lat_micro: 40_000_000, lng_micro: -74_000_000 }, radius_m: 500, vertices: null },
  { id: 'g2', name: 'North zone', shape: 'polygon', center: null, radius_m: null, vertices: [
    { lat_micro: 40_900_000, lng_micro: -73_100_000 }, { lat_micro: 40_900_000, lng_micro: -72_900_000 }, { lat_micro: 41_100_000, lng_micro: -72_900_000 }, { lat_micro: 41_100_000, lng_micro: -73_100_000 }] },
]
const PLACES = [{ id: 'pl1', name: 'HQ', kind: 'office', lat_micro: 40_500_000, lng_micro: -73_500_000, lat: '', lng: '' }]
const ASG = [{ id: 'as1', request_ref: 'R-9', candidate_id: 'van-1', status: 'offered', score: 812, distance_m: 640, expires_at: iso(-60) }]
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

function api(over: (url: string) => Response | undefined = () => undefined) {
  const calls: { url: string; auth?: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, auth: (init.headers as Record<string, string>).Authorization })
    const o = over(url)
    if (o) return o
    if (url.includes('/location/positions')) return json({ items: POS, truncated: false })
    if (url.includes('/geo/geofences')) return json({ items: FENCES, total: 2, limit: 200, offset: 0 })
    if (url.includes('/geo/places')) return json({ items: PLACES, total: 1, limit: 200, offset: 0 })
    if (url.includes('/matching/assignments')) return json({ items: ASG, total: 1, limit: 100, offset: 0 })
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const el = (f: typeof fetch, extra: Record<string, unknown> = {}) => createElement(MapPage, { projectId: 'p', origin: 'http://gen.test', doFetch: f, now: () => NOW, ...extra })
async function load(f: typeof fetch, extra: Record<string, unknown> = {}) {
  const host = await mount(el(f, extra))
  await setInput(q('map-token') as HTMLInputElement, 'TOK')
  await click(q('map-load'))
  return host
}
const setHidden = (h: boolean) => {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => h })
  document.dispatchEvent(new Event('visibilitychange'))
}
const wait = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)) })

describe('MapPage', () => {
  it('explains when no preview origin is configured and fetches nothing', async () => {
    const { f } = api()
    await mount(createElement(MapPage, { projectId: 'p', origin: null, doFetch: f }))
    expect(q('map-no-origin')).not.toBeNull()
    expect(f).not.toHaveBeenCalled()
  })

  it('shows an error (not a crash) when a 2xx answer is not the expected JSON', async () => {
    const { f } = api((u) => (u.includes('/geo/geofences') ? new Response('<html>x</html>', { status: 200 }) : undefined))
    await load(f)
    expect(q('map-fences-error')).not.toBeNull()
  })

  it('asks for a token, then loads all four feeds with a Bearer header and the box query', async () => {
    const { f, calls } = api()
    await mount(el(f))
    expect(q('map-notoken')).not.toBeNull()
    expect(f).not.toHaveBeenCalled()
    expect((q('map-token') as HTMLInputElement).type).toBe('password')
    await setInput(q('map-token') as HTMLInputElement, 'TOK')
    await click(q('map-load'))
    expect(calls.every((c) => c.auth === 'Bearer TOK' && c.url.startsWith('http://gen.test/'))).toBe(true)
    const pc = calls.find((c) => c.url.includes('/location/positions'))!
    expect(pc.url).toContain('min_lat_micro=-90000000&min_lng_micro=-180000000&max_lat_micro=90000000&max_lng_micro=180000000&limit=500')
    expect(calls.some((c) => c.url.includes('/geo/geofences'))).toBe(true)
    expect(calls.some((c) => c.url.includes('/geo/places'))).toBe(true)
    expect(calls.some((c) => c.url.includes('/matching/assignments'))).toBe(true)
  })

  it('draws markers with aria-labels, a cluster, stale styling, fences and places', async () => {
    const { f } = api()
    await load(f)
    expect(qa('map-list-item')).toHaveLength(3)
    const markers = qa('map-marker')
    expect(markers).toHaveLength(1) // van-1 and van-2 are clustered at the fitted zoom
    expect(markers[0].tagName).toBe('BUTTON')
    expect(markers[0].dataset.subject).toBe('van-3')
    expect(markers[0].dataset.freshness).toBe('stale')
    expect(markers[0].getAttribute('aria-label')).toMatch(/van-3 \(courier\), 41\.000000, -73\.000000, 6 min ago, stale/)
    const cl = qa('map-cluster')
    expect(cl).toHaveLength(1)
    expect(cl[0].dataset.count).toBe('2')
    expect(cl[0].getAttribute('aria-label')).toBe('Cluster of 2 subjects, press to zoom in')
    expect(qa('map-fence-circle')).toHaveLength(1)
    expect(qa('map-fence-polygon')).toHaveLength(1)
    expect(qa('map-place')).toHaveLength(1)
  })

  it('clicking a cluster zooms in and splits it into two markers', async () => {
    const { f } = api()
    await load(f)
    await click(q('map-cluster'))
    expect(qa('map-cluster')).toHaveLength(0)
    expect(qa('map-marker').map((m) => m.dataset.subject).sort()).toEqual(['van-1', 'van-2'])
    expect(qa('map-marker')[0].dataset.freshness).toBe('fresh')
    await click(q('map-fit'))
    expect(qa('map-cluster')).toHaveLength(1)
  })

  it('syncs selection between list and markers and shows fences and assignments', async () => {
    const { f } = api()
    await load(f)
    await click(qa('map-list-item')[2])
    expect(qa('map-list-item')[2].getAttribute('aria-pressed')).toBe('true')
    expect(q('map-marker')?.getAttribute('aria-pressed')).toBe('true')
    expect(q('map-details-fences')?.textContent).toBe('Inside: North zone')
    expect(q('map-details-assignments')?.textContent).toMatch(/No open assignment/)
    await click(qa('map-list-item')[0])
    expect(q('map-details-fences')?.textContent).toBe('Inside: Depot')
    expect(q('map-assignment')?.textContent).toBe('Request R-9: offered, 640 m away, score 812')
    await click(q('map-details-close'))
    expect(q('map-details')).toBeNull()
    // selecting through a marker works too
    await click(q('map-marker'))
    expect(q('map-details')?.getAttribute('aria-label')).toBe('Details of van-3')
    expect(qa('map-list-item')[2].getAttribute('aria-pressed')).toBe('true')
  })

  it('refresh refetches, zoom narrows the view and "load only this area" sends a narrower box', async () => {
    const { f, calls } = api()
    await load(f)
    const n = calls.length
    await click(q('map-refresh'))
    expect(calls.length).toBeGreaterThan(n)
    expect(q('map-updated')?.textContent).toBe('Updated 12:00:00 UTC')
    await click(q('map-load-area'))
    const last = calls.filter((c) => c.url.includes('/location/positions')).pop()!
    expect(last.url).not.toContain('min_lat_micro=-90000000')
  })

  it('auto-poll refetches on an interval and pauses while the tab is hidden', async () => {
    const { f, calls } = api()
    await load(f, { pollMs: 25 })
    const count = () => calls.filter((c) => c.url.includes('/location/positions')).length
    const base = count()
    await click(q('map-auto'))
    for (let i = 0; i < 40 && count() <= base + 1; i++) await wait(50)
    expect(count()).toBeGreaterThan(base + 1)
    setHidden(true)
    await flush()
    const paused = count()
    await wait(120)
    expect(count()).toBe(paused)
    setHidden(false)
    for (let i = 0; i < 40 && count() <= paused; i++) await wait(50)
    expect(count()).toBeGreaterThan(paused)
    await click(q('map-auto'))
    await flush()
    const off = count()
    await wait(100)
    expect(count()).toBe(off)
  })

  it('shows empty, error and not-enabled states', async () => {
    const e = api((u) => (u.includes('/location/positions') ? json({ items: [], truncated: false }) : u.includes('/geo/geofences') ? json({ code: 'not_found' }, 404) : undefined))
    await load(e.f)
    expect(q('map-positions-empty')).not.toBeNull()
    expect(q('map-geo-off')).not.toBeNull()
    expect(qa('map-marker')).toHaveLength(0)
  })

  it('maps a 403 and a network failure to readable errors', async () => {
    const a = api((u) => (u.includes('/location/positions') ? json({ code: 'forbidden', message: 'x', details: [] }, 403) : undefined))
    await load(a.f)
    expect(q('map-positions-error')?.textContent).toMatch(/role may not read/)
    const b = api(() => { throw new Error('offline') })
    await load(b.f)
    expect(q('map-positions-error')?.textContent).toBe('offline')
  })

  it('warns when the server truncated the positions', async () => {
    const { f } = api((u) => (u.includes('/location/positions') ? json({ items: POS, truncated: true }) : undefined))
    await load(f)
    expect(q('map-truncated')).not.toBeNull()
  })

  it('has no axe violations (loaded, with a selection)', async () => {
    const { f } = api()
    const host = await load(f)
    await click(qa('map-list-item')[0])
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
