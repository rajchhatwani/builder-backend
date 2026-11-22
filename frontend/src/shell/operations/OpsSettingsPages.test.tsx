import axe from 'axe-core'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GeoSettingsPage, LocationSettingsPage, MatchingSettingsPage, PredictionSettingsPage } from './OpsSettingsPages'

const m = vi.hoisted(() => ({ getBlock: vi.fn(), putBlock: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: m }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount(el: ReturnType<typeof createElement>) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(el) })
  await act(async () => { await Promise.resolve() })
}
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null; Object.values(m).forEach((f) => f.mockReset()) })
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const type = async (el: HTMLInputElement, v: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const field = (path: string) => host.querySelector<HTMLInputElement>(`[data-field-path="${path}"] input`)!

const OPS = {
  geo: { read_roles: ['admin'], write_roles: ['admin'], provider: 'fake', grid_cell_micro: 10000, max_places: 100000, max_geofences: 1000, max_polygon_vertices: 200, max_radius_m: 20000000 },
  location: { read_roles: ['admin'], write_roles: ['admin'], history_cap: 100, max_subjects: 100000 },
  matching: { read_roles: ['admin'], assign_roles: ['admin'], weights: { distance: 1000, load: 0, rating: 0 }, max_distance_m: 20000, max_load: 10, offer_ttl_seconds: 300 },
  prediction: { read_roles: ['admin'], write_roles: ['admin'], model_id: 'fake-linear-v1', unit: 'unit', interval_bp: 2000 },
}
const PACKS = { ai: { providers: [] }, money: { ledger: { read_roles: ['admin'] } }, operations: OPS }

const PAGES = [
  { block: 'geo', Page: GeoSettingsPage, h1: 'Geo settings', focus: 'max_places', val: '5', check: (b: any) => b.max_places === 5 && b.provider === 'fake' },
  { block: 'location', Page: LocationSettingsPage, h1: 'Location settings', focus: 'history_cap', val: '25', check: (b: any) => b.history_cap === 25 },
  { block: 'matching', Page: MatchingSettingsPage, h1: 'Matching settings', focus: 'weights.load', val: '3', check: (b: any) => b.weights.load === 3 && b.weights.distance === 1000 },
  { block: 'prediction', Page: PredictionSettingsPage, h1: 'Prediction settings', focus: 'interval_bp', val: '1500', check: (b: any) => b.interval_bp === 1500 },
] as const

describe.each(PAGES)('$block settings page', ({ block, Page, h1, focus, val, check }) => {
  it('renders once, saves, and the PUT only changes this block', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: { packs: unknown }) => ({ packs: b.packs, version: 4 }))
    await mount(createElement(Page, { projectId: 'p' }))
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(host.querySelector('h1')?.textContent).toBe(h1)
    expect(m.getBlock).toHaveBeenCalledWith('p', 'packs')
    await type(field(focus), val)
    await act(async () => { btn(/^Save$/).click() })
    expect(m.putBlock).toHaveBeenCalledTimes(1)
    const body = m.putBlock.mock.calls[0][2]
    expect(body.expected_version).toBe(3)
    const { [block]: saved, ...otherOps } = body.packs.operations
    const { [block]: _orig, ...expectedOps } = OPS
    expect(otherOps).toEqual(expectedOps)
    expect(body.packs.ai).toEqual(PACKS.ai)
    expect(body.packs.money).toEqual(PACKS.money)
    expect(check(saved)).toBe(true)
    const rest = { ...saved }
    for (const k of Object.keys(OPS[block])) expect(k in rest).toBe(true)
  })

  it('switches on with the schema defaults when the block is off, leaving other blocks alone', async () => {
    const { [block]: _off, ...others } = OPS
    m.getBlock.mockResolvedValue({ packs: { ...PACKS, operations: others }, version: 1 })
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: { packs: unknown }) => ({ packs: b.packs, version: 2 }))
    await mount(createElement(Page, { projectId: 'p' }))
    expect(host.querySelector('[data-testid=block-off]')).not.toBeNull()
    await act(async () => { btn(/^Switch on/).click() })
    const ops = m.putBlock.mock.calls[0][2].packs.operations
    expect(ops[block]).toEqual(OPS[block])
    for (const [k, v] of Object.entries(others)) expect(ops[k]).toEqual(v)
  })

  it('has no axe violations', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    await mount(createElement(Page, { projectId: 'p' }))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})

describe('geo provider', () => {
  it('is never shown as a field but stays fake in the saved block', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: { packs: unknown }) => ({ packs: b.packs, version: 4 }))
    await mount(createElement(GeoSettingsPage, { projectId: 'p' }))
    expect(host.querySelector('[data-field-path="provider"]')).toBeNull()
    await type(field('max_geofences'), '7')
    await act(async () => { btn(/^Save$/).click() })
    expect(m.putBlock.mock.calls[0][2].packs.operations.geo.provider).toBe('fake')
  })
})
