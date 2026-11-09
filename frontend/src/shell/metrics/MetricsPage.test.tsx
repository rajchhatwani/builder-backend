import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { MetricRead, ReportRead, ReportRunRead } from '../../api/types'
import { MetricsPage } from './MetricsPage'

const m = vi.hoisted(() => ({
  spec: vi.fn(), listMetrics: vi.fn(), listReports: vi.fn(), createMetric: vi.fn(), updateMetric: vi.fn(), deleteMetric: vi.fn(), getMetricValue: vi.fn(),
  createReport: vi.fn(), updateReport: vi.fn(), deleteReport: vi.fn(), runReport: vi.fn(), listReportRuns: vi.fn(), getReportValue: vi.fn(),
}))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  api: {
    getSpecJson: m.spec, listMetrics: m.listMetrics, listReports: m.listReports, createMetric: m.createMetric, updateMetric: m.updateMetric,
    deleteMetric: m.deleteMetric, getMetricValue: m.getMetricValue, createReport: m.createReport, updateReport: m.updateReport,
    deleteReport: m.deleteReport, runReport: m.runReport, listReportRuns: m.listReportRuns, getReportValue: m.getReportValue,
  },
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const SPEC = { entities: [{ name: 'Invoice', fields: [{ name: 'invoice_no', type: 'string' }, { name: 'amount', type: 'decimal' }] }] }
const metric = (key: string, label: string, extra: Partial<MetricRead['definition']> = {}): MetricRead => ({
  key, version: 1, updated_at: '2026-11-09T00:00:00Z',
  definition: { key, label, entity: 'Invoice', agg: 'sum', field: 'amount', filter: [], ...extra },
})
const TOTAL = metric('total', 'Total billed', { unit: 'USD' })
const COUNT = metric('n', 'Invoices', { agg: 'count', field: null })
const report = (id: string, name: string, keys: string[]): ReportRead => ({
  id, name, metric_keys: keys, schedule: '0 8 * * *', timezone: 'UTC', enabled: true, last_scheduled_for: null, updated_at: '2026-11-09T00:00:00Z',
})
const EXACT = '12345678901234567890.123456789'

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() })
async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(MetricsPage, { projectId: 'p' })) })
  await flush()
}
const q = (s: string) => host.querySelector(s) as HTMLElement | null
const qa = (s: string) => [...host.querySelectorAll(s)] as HTMLElement[]
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.getAttribute('aria-label') ?? b.textContent ?? ''))!
const click = async (re: RegExp) => { await act(async () => { btn(re).click() }); await flush() }
async function type(el: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => { set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })) })
}
async function choose(el: HTMLSelectElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
  await act(async () => { set.call(el, value); el.dispatchEvent(new Event('change', { bubbles: true })) })
}
const check = async (el: HTMLInputElement) => { await act(async () => { el.click() }); await flush() }

beforeEach(() => {
  for (const f of Object.values(m)) f.mockReset()
  m.spec.mockResolvedValue(SPEC)
  m.listMetrics.mockResolvedValue({ items: [TOTAL, COUNT], total: 2 })
  m.listReports.mockResolvedValue({ items: [], total: 0 })
  m.getMetricValue.mockImplementation(async (_p: string, key: string) => ({ key, version: 1, value: key === 'total' ? EXACT : 7, groups: null, computed_at: '' }))
  m.listReportRuns.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
})
afterEach(async () => {
  if (root) await act(async () => { root!.unmount() })
  root = null
  host?.remove()
})

describe('MetricsPage metrics tab', () => {
  it('shows each metric with its exact current value', async () => {
    await mount()
    expect(q('h1')!.textContent).toBe('Metrics & reports')
    expect(qa('[data-testid=metric-row]')).toHaveLength(2)
    expect(q('[data-testid=metric-value-total]')!.textContent).toBe('12,345,678,901,234,567,890.123456789 USD')
    expect(q('[data-testid=metric-value-n]')!.textContent).toBe('7')
  })

  it('shows an empty state', async () => {
    m.listMetrics.mockResolvedValue({ items: [], total: 0 })
    await mount()
    expect(q('[data-testid=metrics-empty]')).not.toBeNull()
  })

  it('shows an error state and retries', async () => {
    m.listMetrics.mockRejectedValueOnce(new ApiError(500, { code: 'internal', message: 'boom', details: [] }))
    await mount()
    expect(q('[data-testid=metrics-error]')!.textContent).toContain('boom')
    await click(/Try again/)
    expect(qa('[data-testid=metric-row]')).toHaveLength(2)
  })

  it('creates a metric with typed filters, offering numeric fields only for sum', async () => {
    m.createMetric.mockResolvedValue(TOTAL)
    await mount()
    await click(/New metric/)
    const field = q('#m-field') as HTMLSelectElement
    await choose(q('#m-agg') as HTMLSelectElement, 'sum')
    expect([...field.options].map((o) => o.value)).toEqual(['', 'amount'])
    await type(q('#m-key') as HTMLInputElement, 'open_total')
    await type(q('#m-label') as HTMLInputElement, 'Open total')
    await choose(q('#m-field') as HTMLSelectElement, 'amount')
    await click(/Add filter/)
    await choose(q('[aria-label="Filter 1 field"]') as HTMLSelectElement, 'amount')
    await choose(q('[aria-label="Filter 1 operator"]') as HTMLSelectElement, 'gt')
    await type(q('[aria-label="Filter 1 value"]') as HTMLInputElement, '10.10')
    await click(/Create metric/)
    expect(m.createMetric).toHaveBeenCalledWith('p', {
      key: 'open_total', label: 'Open total', entity: 'Invoice', agg: 'sum', field: 'amount', filter: [{ field: 'amount', op: 'gt', value: '10.10' }],
    })
  })

  it('blocks a bad form with hints and sends nothing', async () => {
    await mount()
    await click(/New metric/)
    await click(/Create metric/)
    expect(m.createMetric).not.toHaveBeenCalled()
    expect(q('#m-key-err')!.textContent).toMatch(/lowercase/)
  })

  it('explains a metric that is still in use when deleting', async () => {
    m.deleteMetric.mockRejectedValue(new ApiError(409, { code: 'metric_in_use', message: 'the metric is used by report(s): Weekly', details: [] }))
    await mount()
    await click(/^Delete Total billed/)
    await click(/Confirm delete Total billed/)
    expect(m.deleteMetric).toHaveBeenCalledWith('p', 'total')
    expect(q('[data-testid=metrics-action-error]')!.textContent).toMatch(/still used by a report.*Weekly/)
  })

  it('shows a quota error from saving', async () => {
    m.createMetric.mockRejectedValue(new ApiError(429, { code: 'quota_exceeded', message: 'quota', details: [{ limit: 10, used: 10, period_end: '2026-12-01T00:00:00Z' }] }))
    await mount()
    await click(/New metric/)
    await type(q('#m-key') as HTMLInputElement, 'k')
    await type(q('#m-label') as HTMLInputElement, 'K')
    await click(/Create metric/)
    expect(q('[data-testid=metric-form-error]')!.textContent).toMatch(/allows 10.*2026-12-01/)
  })
})

describe('MetricsPage reports tab', () => {
  const R1 = report('r1', 'Weekly', ['total', 'n'])
  const R2 = report('r2', 'Board pack', ['total'])
  const RUN: ReportRunRead = { id: 'x', report_id: 'r1', scheduled_for: '2026-11-09T08:00:00Z', status: 'ok', values: { total: { value: EXACT }, n: { value: 7 } }, created_at: '' }
  beforeEach(() => {
    m.listReports.mockResolvedValue({ items: [R1, R2], total: 2 })
    m.getReportValue.mockImplementation(async (_p: string, id: string) => ({
      report_id: id, computed_at: '', values: id === 'r1' ? { total: { value: EXACT }, n: { value: 7 } } : { total: { value: EXACT } },
    }))
  })

  const openReports = async () => { await mount(); await click(/^Reports$/) }

  it('lists reports with a readable schedule', async () => {
    await openReports()
    expect(qa('[data-testid=report-row]')).toHaveLength(2)
    expect(q('[data-testid=report-row]')!.textContent).toContain('Every day at 08:00')
  })

  it('shows an empty state', async () => {
    m.listReports.mockResolvedValue({ items: [], total: 0 })
    await openReports()
    expect(q('[data-testid=reports-empty]')).not.toBeNull()
  })

  it('shows the same metric identically in two reports', async () => {
    await openReports()
    await click(/Open report Weekly/)
    const first = q('[data-testid=report-value-total]')!.textContent
    await click(/Open report Board pack/)
    const second = q('[data-testid=report-value-total]')!.textContent
    expect(first).toBe('12,345,678,901,234,567,890.123456789 USD')
    expect(second).toBe(first)
  })

  it('creates a report from a preset schedule and picked metrics', async () => {
    m.createReport.mockResolvedValue(R1)
    await openReports()
    await click(/New report/)
    await click(/Create report/)
    expect(m.createReport).not.toHaveBeenCalled()
    await type(q('#r-name') as HTMLInputElement, ' Weekly ')
    await check(host.querySelectorAll('fieldset input[type=checkbox]')[0] as HTMLInputElement)
    await choose(q('#r-sched') as HTMLSelectElement, 'weekdays')
    await click(/Create report/)
    expect(m.createReport).toHaveBeenCalledWith('p', { name: 'Weekly', metric_keys: ['total'], schedule: '0 8 * * 1-5', timezone: 'UTC', enabled: true })
  })

  it('runs now and shows run history', async () => {
    m.runReport.mockResolvedValue(RUN)
    await openReports()
    await click(/Open report Weekly/)
    expect(q('[data-testid=report-no-runs]')).not.toBeNull()
    m.listReportRuns.mockResolvedValue({ items: [RUN], total: 1, limit: 20, offset: 0 })
    await click(/Run now/)
    expect(m.runReport).toHaveBeenCalledWith('p', 'r1')
    expect(q('[data-testid=report-run]')!.textContent).toContain('Total billed 12,345,678,901,234,567,890.123456789 USD; Invoices 7')
  })

  it('shows a quota error from Run now and a live value error', async () => {
    m.runReport.mockRejectedValue(new ApiError(429, { code: 'quota_exceeded', message: 'quota', details: [{ limit: 3, used: 3 }] }))
    m.getReportValue.mockRejectedValue(new ApiError(422, { code: 'metric_too_large', message: 'too many', details: [] }))
    await openReports()
    await click(/Open report Weekly/)
    expect(q('[data-testid=report-value-error]')!.textContent).toMatch(/too many records/)
    await click(/Run now/)
    expect(q('[data-testid=report-run-error]')!.textContent).toMatch(/allows 3/)
  })
})
