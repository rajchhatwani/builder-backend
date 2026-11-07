import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { PlanReviewPage } from './PlanReviewPage'

const m = vi.hoisted(() => ({ listApprovals: vi.fn(), decide: vi.fn() }))
vi.mock('./aiApi', () => ({ aiApi: m }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const RUN = '22222222-aaaa-bbbb'
const mk = (o: Record<string, unknown> = {}) => ({
  id: 'a1', run_id: RUN, project_id: 'p', kind: 'A', subject: 'plan', payload: { plan: { entities: ['Invoice', 'Customer'], hooks: [], zones: [], dependencies: [] } },
  risk_flags: [], state: 'pending', requires_owner: false, bound_spec_hash: 'h', decided_at: null, decision_note: null, expires_at: '2099-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z', ...o,
})
let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); Object.values(m).forEach((f) => f.mockReset()); window.location.hash = '' })
async function mount() {
  window.location.hash = `#/p/p/plan?run=${RUN}`
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  await act(async () => { root!.render(createElement(PlanReviewPage, { projectId: 'p' })) })
  await act(async () => { await Promise.resolve() })
}
const q = (id: string) => host.querySelector(`[data-testid=${id}]`)
const click = async (el: Element | null) => { await act(async () => { (el as HTMLElement).click() }) }

describe('Plan review', () => {
  it('approves an unedited plan without a plan in the body', async () => {
    m.listApprovals.mockResolvedValue([mk()])
    await mount()
    m.decide.mockResolvedValue(mk({ state: 'approved' }))
    await click(q('plan-approve'))
    expect(m.decide).toHaveBeenCalledWith('p', 'a1', true, '', undefined)
  })
  it('approves an edited plan by sending it in the decision', async () => {
    m.listApprovals.mockResolvedValue([mk()])
    await mount()
    await click(host.querySelector('tbody button'))
    expect(q('plan-approve')?.textContent).toContain('edited plan')
    m.decide.mockResolvedValue(mk({ state: 'approved' }))
    await click(q('plan-approve'))
    expect(m.decide).toHaveBeenCalledWith('p', 'a1', true, '', { entities: ['Customer'], hooks: [], zones: [], dependencies: [] })
    expect(q('plan-done')?.textContent).toContain('edited plan was approved')
  })
  it('explains 422 plan_empty', async () => {
    m.listApprovals.mockResolvedValue([mk({ payload: { plan: { entities: ['Invoice'] } } })])
    await mount()
    await click(host.querySelector('tbody button'))
    m.decide.mockRejectedValue(new ApiError(422, { code: 'plan_empty', message: 'plan is empty', details: [] }))
    await click(q('plan-approve'))
    expect(host.querySelector('[role=alert]')?.textContent).toContain('edited plan is empty')
  })
  it('shows a decided plan read-only with what it was edited from', async () => {
    m.listApprovals.mockResolvedValue([mk({ state: 'approved', decided_by: 'abcdef12-0000', payload: { plan: { entities: ['Customer'] }, edited_from: { entities: ['Invoice', 'Customer'] } } })])
    await mount()
    expect(m.listApprovals).toHaveBeenCalledWith('p', { run_id: RUN })
    expect(q('plan-state')?.textContent).toContain('Approved')
    expect(q('plan-edited-from')?.textContent).toContain('Invoice')
    expect(q('plan-edited-from')?.textContent).toContain('abcdef12')
    expect(q('plan-approve')).toBeNull()
  })
})
