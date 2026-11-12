import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { UiProvider } from '../../components/Ui'

import { OperationsPage } from './OperationsPage'

const m = vi.hoisted(() => ({ adminOperations: vi.fn(), adminRunGolive: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: m }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const GOLIVE = {
  ran_at: '2026-11-13T10:00:00Z', ok: false, passed: 1, failed: 1, warnings: 1, skipped: 1,
  checks: [
    { check: 'P1 runner configured', status: 'pass', detail: 'ok' },
    { check: 'P3/P5 RLS API role', status: 'fail', detail: 'role is a superuser' },
    { check: 'P4 proxy headers', status: 'warn', detail: 'not set' },
    { check: 'P2 firewall', status: 'skipped', detail: 'needs root' },
  ],
}
const OPS = {
  generated_at: '2026-11-13T10:00:00Z',
  scheduler: { jobs: [
    { job: 'reports', interval_seconds: 60, last_run_at: '2026-11-13T09:59:00Z', last_status: 'ok', last_error: null, runs: 12, next_expected_at: '2026-11-13T10:00:00Z', stale: false },
    { job: 'idle_sweep', interval_seconds: 3600, last_run_at: null, last_status: null, last_error: null, runs: 0, next_expected_at: null, stale: true },
  ] },
  idle_workspaces: { ttl_days: 14, live_workspaces: 5, idle_past_ttl: 2 },
  reports: { enabled_schedules: 3, disabled_schedules: 1, last_run_at: null, next_run_at: null },
  usage_defaults: [{ metric: 'generations', unit: 'runs', period: 'month', default_limit: 100 }, { metric: 'storage', unit: 'MB', period: 'none', default_limit: null }],
  key_provider: { kind: 'file', healthy: false, active_key_id: null, key_count: 0, error: 'FileNotFoundError' },
  golive: GOLIVE,
}

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount(readOnly = false) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(UiProvider, null, createElement(OperationsPage, { readOnly }))) })
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const tid = (id: string) => host.querySelector(`[data-testid="${id}"]`)
afterEach(() => { act(() => root?.unmount()); host?.remove(); document.body.innerHTML = ''; root = null; Object.values(m).forEach((f) => f.mockReset()) })

describe('OperationsPage', () => {
  it('renders scheduler, idle, reports, key provider and go-live results', async () => {
    m.adminOperations.mockResolvedValue(OPS)
    await mount()
    expect(host.querySelector('h1')?.textContent).toBe('Operations')
    const rows = [...host.querySelectorAll('[data-testid=job-row]')]
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('1 min')
    expect(rows[0].querySelector('[data-testid=job-state]')?.textContent).toBe('On time')
    expect(rows[1].querySelector('[data-testid=job-state]')?.textContent).toBe('Stale')
    expect(rows[1].textContent).toContain('never')
    expect(tid('idle-text')?.textContent).toContain('14 days')
    expect(tid('idle-text')?.textContent).toContain('2 past the limit')
    expect(tid('reports-text')?.textContent).toContain('3 enabled, 1 disabled')
    expect(tid('reports-text')?.textContent).toContain('not scheduled')
    expect(tid('key-state')?.getAttribute('data-healthy')).toBe('false')
    expect(tid('key-state')?.textContent).toContain('FileNotFoundError')
    expect(tid('usage-defaults')?.textContent).toContain('Unlimited')
    expect([...host.querySelectorAll('[data-testid=golive-row]')].map((r) => r.getAttribute('data-status'))).toEqual(['pass', 'fail', 'warn', 'skipped'])
    expect(tid('golive-results')?.textContent).toContain('role is a superuser')
    expect(tid('golive-summary')?.textContent).toContain('Not ready')
  })

  it('shows the error state and retries', async () => {
    m.adminOperations.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce(OPS)
    await mount()
    expect(host.querySelector('[role=alert]')?.textContent).toContain('boom')
    await act(async () => { [...host.querySelectorAll('button')].find((b) => /try again/i.test(b.textContent ?? ''))!.click(); await new Promise((r) => setTimeout(r, 0)) })
    expect(host.querySelector('h1')?.textContent).toBe('Operations')
    expect(tid('scheduler')).not.toBeNull()
  })

  it('shows an empty state when no job has reported', async () => {
    m.adminOperations.mockResolvedValue({ ...OPS, scheduler: { jobs: [] }, usage_defaults: [] })
    await mount()
    expect(tid('no-jobs')).not.toBeNull()
  })

  it('platform admin re-runs the go-live checks and sees the new results', async () => {
    m.adminOperations.mockResolvedValue(OPS)
    m.adminRunGolive.mockResolvedValue({ ...GOLIVE, ok: true, failed: 0, checks: [{ check: 'P6 key provider', status: 'pass', detail: 'fine' }] })
    await mount()
    await act(async () => { (tid('golive-run') as HTMLElement).click(); await new Promise((r) => setTimeout(r, 0)) })
    expect(m.adminRunGolive).toHaveBeenCalledTimes(1)
    expect(host.querySelectorAll('[data-testid=golive-row]')).toHaveLength(1)
    expect(tid('golive-summary')?.textContent).toContain('Ready')
  })

  it('shows a run failure as an alert', async () => {
    m.adminOperations.mockResolvedValue(OPS)
    m.adminRunGolive.mockRejectedValue(new ApiError(403, 'forbidden'))
    await mount()
    await act(async () => { (tid('golive-run') as HTMLElement).click(); await new Promise((r) => setTimeout(r, 0)) })
    expect(tid('golive-error')?.textContent).toContain('Only platform admins')
  })

  it('hides the run button for read-only staff but still shows results', async () => {
    m.adminOperations.mockResolvedValue(OPS)
    await mount(true)
    expect(tid('golive-run')).toBeNull()
    expect(tid('golive-results')).not.toBeNull()
  })
})
