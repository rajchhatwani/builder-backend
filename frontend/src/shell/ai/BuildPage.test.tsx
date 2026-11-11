import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { BuildPage } from './BuildPage'

const m = vi.hoisted(() => ({ getRun: vi.fn(), listApprovals: vi.fn(), listRuns: vi.fn(), platformBudget: vi.fn(), listPreviews: vi.fn(), cancelRun: vi.fn(), resumeRun: vi.fn(), pauseRun: vi.fn(), runGates: vi.fn() }))
vi.mock('./aiApi', () => ({ aiApi: m }))
vi.mock('./StageTabs', () => ({ StageTabs: (p: { workspaceId: string; onDirtyChange?: (d: boolean) => void }) => createElement('div', { 'data-testid': 'stage-mock' }, p.workspaceId, createElement('button', { 'data-testid': 'make-dirty', onClick: () => p.onDirtyChange?.(true) })) }))
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
const q = (id: string) => host.querySelector(`[data-testid=${id}]`) as HTMLElement | null

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
  it('S3-001: after Resume on a stopped run the page keeps polling while the resume request is open', async () => {
    vi.useFakeTimers()
    try {
      await mount(run())
      let finish: (v?: unknown) => void = () => undefined
      m.resumeRun.mockReturnValue(new Promise((r) => { finish = r }))
      await act(async () => { (q('run-resume') as HTMLElement).click() })
      m.getRun.mockClear()
      m.getRun.mockResolvedValue(run({ state: 'running', phase: 'build' }))
      await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
      expect(m.getRun).toHaveBeenCalled()
      expect(q('chip-state')?.textContent).not.toBe('Stopped')
      await act(async () => { finish() })
    } finally { vi.useRealTimers() }
  })
  it('S3-002: a slow response for the previous run never replaces the run that was opened later', async () => {
    const A = 'a1a1a1a1-aaaa'; const B = 'b2b2b2b2-bbbb'
    let slowA: (v: unknown) => void = () => undefined
    m.getRun.mockImplementation((_p: string, id: string) => (id === A ? new Promise((r) => { slowA = r }) : Promise.resolve(run({ id: B, goal: 'goal of B', state: 'applied' }))))
    m.listApprovals.mockResolvedValue([]); m.listPreviews.mockResolvedValue([]); m.platformBudget.mockResolvedValue(null)
    window.location.hash = `#/p/p/build?run=${A}`
    host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
    await act(async () => { root!.render(createElement(BuildPage, { projectId: 'p' })) })
    await act(async () => { window.location.hash = `#/p/p/build?run=${B}`; window.dispatchEvent(new HashChangeEvent('hashchange')) })
    await act(async () => { await Promise.resolve() })
    expect(q('run-goal')?.textContent).toBe('goal of B')
    await act(async () => { slowA(run({ id: A, goal: 'goal of A' })) })
    expect(q('run-goal')?.textContent).toBe('goal of B')
  })

  const future = new Date(Date.now() + 86_400_000).toISOString()
  const appr = (o: Record<string, unknown> = {}) => ({ id: 'ap1', run_id: 'a1a1a1a1-aaaa', project_id: 'p', kind: 'C', subject: 'review it', payload: {}, risk_flags: [], state: 'pending', requires_owner: false, bound_spec_hash: 'h', decided_at: null, decision_note: null, expires_at: future, created_at: future, ...o })

  it('S3-013: Take over keeps the dialog open and shows the error when the cancel fails', async () => {
    await mount(run({ state: 'running' }))
    m.cancelRun.mockRejectedValue(new ApiError(409, { code: 'run_finished', message: 'finished', details: [] }))
    await act(async () => { (q('run-takeover') as HTMLElement).click() })
    await act(async () => { (q('takeover-yes') as HTMLElement).click() })
    await act(async () => { await Promise.resolve() })
    expect(q('takeover-confirm')).not.toBeNull()
    expect(q('build-error')?.textContent).toContain('run_finished')
    m.cancelRun.mockResolvedValue({})
    await act(async () => { (q('takeover-yes') as HTMLElement).click() })
    await act(async () => { await Promise.resolve() })
    expect(q('takeover-confirm')).toBeNull()
  })
  it('S3-014: the takeover dialog takes focus, Escape closes it and focus returns to the button', async () => {
    await mount(run({ state: 'running' }))
    await act(async () => { (q('run-takeover') as HTMLElement).click() })
    expect(document.activeElement).toBe(q('takeover-confirm'))
    await act(async () => { q('takeover-confirm')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(q('takeover-confirm')).toBeNull()
    expect(document.activeElement).toBe(q('run-takeover'))
  })
  it('S3-014: the stage tablist uses roving tabindex and arrow keys', async () => {
    await mount(run())
    const tabs = () => Array.from(host.querySelectorAll('[role=tab]')) as HTMLElement[]
    expect(tabs().map((t) => t.tabIndex)).toEqual([0, -1, -1, -1, -1, -1])
    await act(async () => { tabs()[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) })
    expect(tabs()[1].getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs()[1])
    expect(tabs().map((t) => t.tabIndex)).toEqual([-1, 0, -1, -1, -1, -1])
    await act(async () => { tabs()[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true })) })
    expect(tabs()[0].getAttribute('aria-selected')).toBe('true')
  })
  it('S3-015: an expired-but-pending approval is not listed as waiting and shows as expired', async () => {
    window.location.hash = '#/p/p/build?run=a1a1a1a1-aaaa'
    m.getRun.mockResolvedValue(run({ state: 'awaiting_approval' })); m.platformBudget.mockResolvedValue(null); m.listPreviews.mockResolvedValue([])
    m.listApprovals.mockResolvedValue([appr({ expires_at: '2020-01-01T00:00:00Z' })])
    host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
    await act(async () => { root!.render(createElement(BuildPage, { projectId: 'p' })) })
    await act(async () => { await Promise.resolve() })
    expect(q('pending-approvals')).toBeNull()
    expect(q('gates-table')?.textContent).toContain('expired')
    expect(q('gates-table')?.textContent).not.toContain('pending')
  })
  it('S3-010: switching to another run with unsaved code asks first; declining stays, accepting switches', async () => {
    const A = 'a1a1a1a1-aaaa'; const B = 'b2b2b2b2-bbbb'
    m.getRun.mockImplementation((_p: string, id: string) => Promise.resolve(run({ id, goal: id === A ? 'goal of A' : 'goal of B' })))
    m.listApprovals.mockResolvedValue([]); m.listPreviews.mockResolvedValue([]); m.platformBudget.mockResolvedValue(null)
    window.location.hash = `#/p/p/build?run=${A}`
    host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
    await act(async () => { root!.render(createElement(BuildPage, { projectId: 'p' })) })
    await act(async () => { await Promise.resolve() })
    await act(async () => { (host.querySelector('#tab-stage') as HTMLElement).click() })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    await act(async () => { (q('make-dirty') as HTMLElement).click() })
    const conf = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const go = async () => { await act(async () => { window.location.hash = `#/p/p/build?run=${B}`; window.dispatchEvent(new HashChangeEvent('hashchange')) }); await act(async () => { await Promise.resolve() }); await act(async () => { await Promise.resolve() }) }
    await go()
    expect(conf).toHaveBeenCalledTimes(1)
    expect(window.location.hash).toContain(A)
    expect(q('run-goal')?.textContent).toBe('goal of A')
    conf.mockReturnValue(true)
    await go()
    expect(q('run-goal')?.textContent).toBe('goal of B')
    conf.mockRestore()
  })
  it('S3-017: a live run polls every 3 s and unmounting cancels the timer', async () => {
    vi.useFakeTimers()
    try {
      await mount(run({ state: 'running' }))
      m.getRun.mockClear()
      await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
      expect(m.getRun).toHaveBeenCalledTimes(1)
      await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
      expect(m.getRun).toHaveBeenCalledTimes(2)
      act(() => root?.unmount()); root = null
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
      expect(m.getRun).toHaveBeenCalledTimes(2)
    } finally { vi.useRealTimers() }
  })
  it('S3-017: a finished run is not polled', async () => {
    vi.useFakeTimers()
    try {
      await mount(run({ state: 'applied' }))
      m.getRun.mockClear()
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
      expect(m.getRun).not.toHaveBeenCalled()
    } finally { vi.useRealTimers() }
  })
})

describe('FX-12 / 6a: pause, gates, focus trap, leave guard, placeholders', () => {
  it('Pause is enabled only on a running build, calls the API, and shows the paused chip', async () => {
    await mount(run({ state: 'running' }))
    const pause = q('run-pause') as HTMLButtonElement
    expect(pause.disabled).toBe(false)
    m.pauseRun.mockResolvedValue(run({ state: 'running', paused_at: '2026-01-01T00:00:00Z' }))
    m.getRun.mockResolvedValue(run({ state: 'running', paused_at: '2026-01-01T00:00:00Z' }))
    await act(async () => { pause.click() })
    await act(async () => { await Promise.resolve() })
    expect(m.pauseRun).toHaveBeenCalledWith('p', 'a1a1a1a1-aaaa')
    expect(q('chip-paused')).not.toBeNull()
    expect((q('run-pause') as HTMLButtonElement).disabled).toBe(true)
  })
  it('Pause is disabled for a stopped or finished run', async () => {
    await mount(run({ state: 'stopped' }))
    expect((q('run-pause') as HTMLButtonElement).disabled).toBe(true)
    expect((q('run-gates') as HTMLButtonElement).disabled).toBe(true)
  })
  it('Pause shows the error envelope when the API refuses', async () => {
    await mount(run({ state: 'running' }))
    m.pauseRun.mockRejectedValue(new ApiError(409, { code: 'illegal_transition', message: 'only a live run that is not applying can be paused', details: [] }))
    await act(async () => { (q('run-pause') as HTMLElement).click() })
    await act(async () => { await Promise.resolve() })
    expect(q('build-error')?.textContent).toContain('can be paused')
  })
  it('Run gates renders the returned report generically (no hardcoded gate ids)', async () => {
    await mount(run({ state: 'running' }))
    m.runGates.mockResolvedValue({ ok: false, failure_count: 2, report_hash: 'abcdef0123456789', failures: [
      { rule_id: 'G-NEW-9', location: 'spec.x', expected: 'a', actual: 'b', hint: 'fix x' },
      { rule_id: 'G-1', location: 'spec.y', expected: 'c', actual: 'd', hint: '' },
    ] })
    await act(async () => { (q('run-gates') as HTMLElement).click() })
    await act(async () => { await Promise.resolve() })
    expect(m.runGates).toHaveBeenCalledWith('p', 'a1a1a1a1-aaaa')
    const rows = [...host.querySelectorAll('[data-testid=gate-row]')]
    expect(rows.map((r) => r.getAttribute('data-gate'))).toEqual(['G-NEW-9', 'G-1'])
    expect(rows[0].querySelector('[data-testid=gate-message]')?.textContent).toBe('fix x')
    expect(rows[1].querySelector('[data-testid=gate-message]')?.textContent).toBe('d')
    expect(q('gate-hash')?.textContent).toBe('abcdef012345')
  })
  it('Run gates shows a pass report and the API error envelope', async () => {
    await mount(run({ state: 'running' }))
    m.runGates.mockResolvedValue({ ok: true, failure_count: 0, report_hash: 'h'.repeat(64), failures: [] })
    await act(async () => { (q('run-gates') as HTMLElement).click() })
    await act(async () => { await Promise.resolve() })
    expect(q('gate-pass')).not.toBeNull()
    m.runGates.mockRejectedValue(new ApiError(429, { code: 'gates_busy', message: 'a gate run for this run is already in progress', details: [] }))
    await act(async () => { (q('run-gates') as HTMLElement).click() })
    await act(async () => { await Promise.resolve() })
    expect(q('build-error')?.textContent).toContain('already in progress')
  })
  it('FX-11: the Diagrams and API tabs say Coming in a later cycle and keep their test id', async () => {
    await mount(run())
    await act(async () => { (host.querySelector('#tab-diagrams') as HTMLElement).click() })
    expect(q('tab-soon')?.textContent).toContain('Coming in a later cycle')
  })
  it('FX-12: Tab and Shift+Tab stay inside the takeover dialog and focus returns on close', async () => {
    await mount(run({ state: 'running' }))
    await act(async () => { (q('run-takeover') as HTMLElement).click() })
    const yes = q('takeover-yes') as HTMLElement; const no = q('takeover-no') as HTMLElement
    const key = (shiftKey: boolean) => { const e = new KeyboardEvent('keydown', { key: 'Tab', shiftKey, bubbles: true, cancelable: true }); q('takeover-confirm')!.dispatchEvent(e); return e }
    no.focus()
    expect(key(false).defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(yes)
    expect(key(true).defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(no)
    yes.focus()
    expect(key(false).defaultPrevented).toBe(false) // middle of the cycle: the browser moves focus itself
    await act(async () => { no.click() })
    expect(document.activeElement).toBe(q('run-takeover'))
  })
  it('S3-010r: leaving the code view tab with unsaved edits asks first', async () => {
    await mount(run())
    await act(async () => { (host.querySelector('#tab-stage') as HTMLElement).click() })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    await act(async () => { (q('make-dirty') as HTMLElement).click() })
    const conf = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await act(async () => { (host.querySelector('#tab-gates') as HTMLElement).click() })
    expect(conf).toHaveBeenCalledTimes(1)
    expect(host.querySelector('#tab-stage')?.getAttribute('aria-selected')).toBe('true')
    conf.mockReturnValue(true)
    await act(async () => { (host.querySelector('#tab-gates') as HTMLElement).click() })
    expect(host.querySelector('#tab-gates')?.getAttribute('aria-selected')).toBe('true')
    conf.mockRestore()
  })
  it('S3-010r: leaving the Build section with unsaved edits asks; declining restores the hash', async () => {
    await mount(run())
    await act(async () => { (host.querySelector('#tab-stage') as HTMLElement).click() })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    await act(async () => { (q('make-dirty') as HTMLElement).click() })
    const before = window.location.hash
    const conf = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await act(async () => { window.location.hash = '#/p/p/rules'; window.dispatchEvent(new HashChangeEvent('hashchange')) })
    expect(conf).toHaveBeenCalledTimes(1)
    expect(window.location.hash).toBe(before)
    conf.mockReturnValue(true)
    await act(async () => { window.location.hash = '#/p/p/rules'; window.dispatchEvent(new HashChangeEvent('hashchange')) })
    expect(window.location.hash).toBe('#/p/p/rules')
    conf.mockRestore()
  })
})
