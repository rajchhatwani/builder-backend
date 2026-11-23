import axe from 'axe-core'
import { act, createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, flush, mount, q, setInput } from '../ai/testUtils'
import { RoutingPage } from './RoutingPage'
import { fakeApi, json } from './opsTestKit'

const api = (over: Parameters<typeof fakeApi>[0] = () => undefined) => fakeApi(over, (_m, u) => {
  if (u.endsWith('/geo/geocode')) return json({ lat_micro: 40_000_000, lng_micro: -74_000_000, lat: '40.000000', lng: '-74.000000', provider: 'fake' })
  if (u.endsWith('/geo/route')) return json({ distance_m: 12_345, duration_s: 1500, mode: 'drive', provider: 'fake' })
  if (u.endsWith('/geo/eta')) return json({ duration_s: 600, distance_m: 5000, arrives_at: '2026-01-01T09:40:00Z', provider: 'fake' })
  if (u.endsWith('/geo/distance')) return json({ distance_m: 777 })
  return json({}, 404)
})
const load = (f: typeof fetch) => mount(createElement(RoutingPage, { projectId: 'p', session: readySession(f) }))
const pts = async (prefix: string, a: [string, string]) => {
  await setInput(q(`${prefix}-lat`) as HTMLInputElement, a[0]); await setInput(q(`${prefix}-lng`) as HTMLInputElement, a[1])
}

describe('RoutingPage', () => {
  it('gates without a session; one h1 and the fake-provider note', async () => {
    const g = await mount(createElement(RoutingPage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('routing-page-no-origin')).not.toBeNull()
    expect(g.querySelectorAll('h1')).toHaveLength(1)
    const host = await load(api().f)
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(host.textContent).toMatch(/deterministic FAKE provider/)
  })

  it('geocodes an address', async () => {
    const { f, to } = api()
    await load(f)
    await click(q('geocode-run'))
    expect(q('geocode-error')?.textContent).toMatch(/Enter an address/)
    await setInput(q('geocode-address') as HTMLInputElement, '1 Main St')
    await click(q('geocode-run'))
    expect(to('POST', '/geo/geocode')[0].body).toEqual({ address: '1 Main St' })
    expect(q('geocode-result')?.textContent).toContain('40.000000')
    expect(q('geocode-result')?.textContent).toContain('fake')
  })

  it('gets a route with integer micro-degrees and the chosen mode, once on a double click', async () => {
    const { f, to } = api()
    await load(f)
    await pts('route-origin', ['40', '-74']); await pts('route-dest', ['40.5', '-73.5'])
    await setInput(q('route-mode') as HTMLSelectElement, 'walk')
    await act(async () => { q('route-run')!.click(); q('route-run')!.click() })
    await flush()
    expect(to('POST', '/geo/route')).toHaveLength(1)
    expect(to('POST', '/geo/route')[0].body).toEqual({ origin: { lat_micro: 40_000_000, lng_micro: -74_000_000 }, destination: { lat_micro: 40_500_000, lng_micro: -73_500_000 }, mode: 'walk' })
    expect(q('route-result')?.textContent).toContain('12.34 km')
    expect(q('route-result')?.textContent).toContain('25 min')
  })

  it('gets an ETA, with and without a departure time', async () => {
    const { f, to } = api()
    await load(f)
    await pts('eta-origin', ['1', '1']); await pts('eta-dest', ['2', '2'])
    await click(q('eta-run'))
    expect(to('POST', '/geo/eta')[0].body).not.toHaveProperty('depart_at')
    expect(q('eta-result')?.textContent).toContain('arrives 2026-01-01T09:40:00Z')
    await setInput(q('eta-depart') as HTMLInputElement, '2026-01-01T09:30')
    await click(q('eta-run'))
    expect(typeof (to('POST', '/geo/eta')[1].body as { depart_at: string }).depart_at).toBe('string')
  })

  it('measures a distance', async () => {
    const { f, to } = api()
    await load(f)
    await pts('distance-a', ['1', '1']); await pts('distance-b', ['2', '2'])
    await click(q('distance-run'))
    expect(to('POST', '/geo/distance')[0].body).toEqual({ a: { lat_micro: 1_000_000, lng_micro: 1_000_000 }, b: { lat_micro: 2_000_000, lng_micro: 2_000_000 } })
    expect(q('distance-result')?.textContent).toContain('777 m')
  })

  it('refuses missing points locally and shows 403 and 422 answers', async () => {
    const { f, calls } = api((_m, u) => (u.endsWith('/geo/route') ? json({ code: 'forbidden', message: 'x' }, 403) : u.endsWith('/geo/eta') ? json({ detail: [{ msg: 'depart_at must be within 10 years of now' }] }, 422) : undefined))
    await load(f)
    await click(q('route-run'))
    expect(q('route-error')?.textContent).toMatch(/both the origin and the destination/)
    expect(calls).toHaveLength(0)
    await pts('route-origin', ['1', '1']); await pts('route-dest', ['2', '2'])
    await click(q('route-run'))
    expect(q('route-error')?.textContent).toMatch(/403.*role/)
    await pts('eta-origin', ['1', '1']); await pts('eta-dest', ['2', '2'])
    await click(q('eta-run'))
    expect(q('eta-error')?.textContent).toBe('depart_at must be within 10 years of now')
  })

  it('has no axe violations', async () => {
    const { f } = api()
    const host = await load(f)
    await pts('route-origin', ['1', '1']); await pts('route-dest', ['2', '2'])
    await click(q('route-run'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
