import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BuildPage } from './BuildPage'

const m = vi.hoisted(() => ({ getRun: vi.fn(), listApprovals: vi.fn(), listRuns: vi.fn(), platformBudget: vi.fn(), listPreviews: vi.fn(), cancelRun: vi.fn(), resumeRun: vi.fn() }))
vi.mock('./aiApi', () => ({ aiApi: m }))
vi.mock('./StageTabs', () => ({ StageTabs: (p: { workspaceId: string }) => createElement('div', { 'data-testid': 'stage-mock' }, p.workspaceId) }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const run = (o: Record<string, unknown> = {}) => ({
  id: 'a1a1a1a1-aaaa', project_id: 'p', workspace_id: 'w1', goal: 'g', state: 'stopped', phase: 'apply', budgets: {}, steps_used: 1, repairs_used: 0, cost_micro_usd: 0,
  stop_code: null, stop_detail: null, started_at: null, finished_at: null, created_at: '', updated_at: '', steps: [], steps_total: 0, limit: 200, offset: 0, ...o,
})
let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); Object.values(m).forEach((f) => f.mockReset()); window.location.hash = '' })
async function mount(r: unknown, budget: unknown = { cap_micro_usd: 10_000_000, spent_micro_usd: 1_000_000, reserved_micro_usd: 0, remaining_micro_usd: 9_000_000 }) {
  window.location.hash = '#/p/p/build?run=a1a1a1a1-aaaa'
  m.getRun.mockResolvedValue(r); m.listApprovals.mockResolvedValue([]); m.listPreviews.mockResolvedValue([]); m.platformBudget.mockResolvedValue(budget)
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  await act(async () => { root!.render(createElement(BuildPage, { projectId: 'p', orgSlug: 'acme' })) })
  await act(async () => { await Promise.resolve() })
}
const q = (id: string) => host.querySelector(`[data-testid=${id}]`)

describe('Build view', () => {
  it('explains apply_conflict with a next step', async () => {
    await mount(run({ stop_code: 'apply_conflict', stop_detail: 'spec moved' }))
    expect(q('stop-info')?.getAttribute('data-code')).toBe('apply_conflict')
    expect(q('stop-text')?.textContent).toContain('Nothing was applied')
    expect(q('stop-next')?.textContent).toContain('owner')
  })
  it('renders system steps friendly and offers See it work after apply', async () => {
    const steps = [
      { id: 's1', seq: 1, kind: 'system', tool_name: null, tool_call_id: null, state: 'done', ok: false, input: null, output: { apply_failed: true }, model: null, created_at: '' },
      { id: 's2', seq: 2, kind: 'system', tool_name: null, tool_call_id: null, state: 'done', ok: true, input: null, output: { draft: 'applied', ops: 2 }, model: null, created_at: '' },
    ]
    await mount(run({ state: 'applied', steps, steps_total: 2 }))
    const rows = host.querySelectorAll('[data-testid=step]')
    expect(rows[0].textContent).toContain('could not be written')
    expect(rows[1].textContent).toContain('was applied to your project')
    expect(q('seeit-link')?.getAttribute('href')).toBe('#/p/p/see')
  })
  it('shows the platform budget and the limit reached state', async () => {
    await mount(run(), { cap_micro_usd: 10_000_000, spent_micro_usd: 10_000_000, reserved_micro_usd: 0, remaining_micro_usd: 0 })
    expect(m.platformBudget).toHaveBeenCalledWith('acme')
    expect(q('budget-platform')?.getAttribute('data-level')).toBe('full')
    expect(q('budget-platform-remaining')?.textContent).toBe('Limit reached')
    expect(q('budget-limit')).not.toBeNull()
  })
  it('warns near 80 percent', async () => {
    await mount(run(), { cap_micro_usd: 10_000_000, spent_micro_usd: 8_200_000, reserved_micro_usd: 0, remaining_micro_usd: 1_800_000 })
    expect(q('budget-platform')?.getAttribute('data-level')).toBe('warn')
  })
  it('mounts the stage tabs for the run workspace', async () => {
    await mount(run())
    await act(async () => { (host.querySelector('#tab-stage') as HTMLElement).click() })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(q('stage-mock')?.textContent).toBe('w1')
  })
})
