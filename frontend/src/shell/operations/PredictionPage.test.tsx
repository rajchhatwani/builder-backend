import axe from 'axe-core'
import { act, createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, flush, mount, q, qa, setInput, typeInto } from '../ai/testUtils'
import { PredictionPage } from './PredictionPage'
import { fakeApi, json } from './opsTestKit'

const R = (id: string, actual: number | null) => ({ id, kind: 'eta', subject_ref: `order-${id}`, model_id: 'fake-linear-v1', unit: 'sec', value: 600, low: 500, high: 700, features: {}, actual, actual_at: null, created_at: '2026-01-01T00:00:00Z' })
const STATS = { logged: 4, with_actual: 2, mae_milli: 1500, abs_error_sum: 3, covered: 1, coverage_bp: 5000 }
const api = (over: Parameters<typeof fakeApi>[0] = () => undefined) => fakeApi(over, (m, u) => {
  if (m !== 'GET') return json({}, 404)
  if (u.includes('/prediction/stats')) return json(STATS)
  if (u.includes('/prediction/records')) return json({ items: [R('1', null), R('2', 650)], total: 2, limit: 100, offset: 0 })
  return json({}, 404)
})
const load = (f: typeof fetch) => mount(createElement(PredictionPage, { projectId: 'p', session: readySession(f) }))

describe('PredictionPage', () => {
  it('gates without a session', async () => {
    const host = await mount(createElement(PredictionPage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('prediction-page-no-origin')).not.toBeNull()
    expect(host.querySelectorAll('h1')).toHaveLength(1)
  })

  it('shows records and stats (count, MAE, interval coverage)', async () => {
    const { f } = api()
    const host = await load(f)
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(qa('record-row')).toHaveLength(2)
    expect(q('stat-logged')?.textContent).toBe('4')
    expect(q('stat-mae')?.textContent).toBe('1.500')
    expect(q('stat-coverage')?.textContent).toBe('50.00% (1 of 2)')
  })

  it('shows n/a when nothing has an actual yet, empty states, and 403', async () => {
    const a = api((_m, u) => (u.includes('/stats') ? json({ logged: 1, with_actual: 0, mae_milli: null, abs_error_sum: 0, covered: 0, coverage_bp: null }) : undefined))
    await load(a.f)
    expect(q('stat-mae')?.textContent).toBe('n/a')
    expect(q('stat-coverage')?.textContent).toBe('n/a')
    const b = api((_m, u) => (u.includes('/stats') ? json({ logged: 0, with_actual: 0, mae_milli: null, abs_error_sum: 0, covered: 0, coverage_bp: null }) : u.includes('/records') ? json({ items: [], total: 0 }) : undefined))
    await load(b.f)
    expect(q('stats-empty')).not.toBeNull()
    expect(q('records-empty')).not.toBeNull()
    const c = api((_m, u) => (u.includes('/records') ? json({ code: 'forbidden', message: 'x' }, 403) : undefined))
    await load(c.f)
    expect(q('records-error')?.textContent).toMatch(/403.*prediction/)
  })

  it('filters records and stats by kind', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('record-filter-kind') as HTMLInputElement, 'eta')
    await setInput(q('record-filter-actual') as HTMLSelectElement, 'false')
    await click(q('record-filter-apply'))
    expect(calls.some((c) => c.url.includes('/prediction/records?') && c.url.includes('kind=eta') && c.url.includes('has_actual=false'))).toBe(true)
    await setInput(q('stats-kind') as HTMLInputElement, 'eta')
    await click(q('stats-apply'))
    expect(calls.some((c) => c.url.includes('/prediction/stats?kind=eta'))).toBe(true)
  })

  it('records a prediction with strict integer features, once, then refreshes records and stats', async () => {
    const { f, to } = api((m, u) => (m === 'POST' && u.endsWith('/prediction/predict') ? json(R('9', null), 201) : undefined))
    await load(f)
    await setInput(q('predict-kind') as HTMLInputElement, 'eta')
    await setInput(q('predict-subject') as HTMLInputElement, 'order-9')
    await typeInto(q('predict-features') as unknown as HTMLTextAreaElement, 'distance_m = 1200\nrush = true\nzone = north')
    const before = to('GET', '/prediction/stats').length
    await act(async () => { q('predict-run')!.click(); q('predict-run')!.click() })
    await flush()
    expect(to('POST', '/prediction/predict')).toHaveLength(1)
    expect(to('POST', '/prediction/predict')[0].body).toEqual({ kind: 'eta', subject_ref: 'order-9', features: { distance_m: 1200, rush: true, zone: 'north' } })
    expect(q('predict-result')?.textContent).toContain('600 sec')
    expect(to('GET', '/prediction/stats').length).toBeGreaterThan(before)
  })

  it('refuses bad input locally and shows API errors', async () => {
    const { f, to } = api((m) => (m === 'POST' ? json({ code: 'forbidden', message: 'x' }, 403) : undefined))
    await load(f)
    await click(q('predict-run'))
    expect(q('predict-error')?.textContent).toMatch(/Kind/)
    await setInput(q('predict-kind') as HTMLInputElement, 'eta')
    await setInput(q('predict-subject') as HTMLInputElement, 's')
    await typeInto(q('predict-features') as unknown as HTMLTextAreaElement, 'oops')
    await click(q('predict-run'))
    expect(q('predict-error')?.textContent).toMatch(/name = value/)
    expect(to('POST', '/predict')).toHaveLength(0)
    await typeInto(q('predict-features') as unknown as HTMLTextAreaElement, 'a = 1')
    await click(q('predict-run'))
    expect(q('predict-error')?.textContent).toMatch(/403.*write/)
  })

  it('records an actual value only for rows without one', async () => {
    const { f, to } = api((m, u) => (m === 'POST' && u.includes('/actual') ? json(R('1', 640)) : undefined))
    await load(f)
    expect(qa('actual-input')).toHaveLength(1)
    await setInput(q('actual-input') as HTMLInputElement, '6.5')
    await click(q('actual-save'))
    expect(q('actual-error')?.textContent).toMatch(/whole number/)
    expect(to('POST', '/actual')).toHaveLength(0)
    await setInput(q('actual-input') as HTMLInputElement, '640')
    await click(q('actual-save'))
    expect(to('POST', '/prediction/records/1/actual')[0].body).toEqual({ actual: 640 })
  })

  it('has no axe violations', async () => {
    const { f } = api()
    const host = await load(f)
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
