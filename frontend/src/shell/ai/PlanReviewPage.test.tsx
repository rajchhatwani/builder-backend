import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { PlanReviewPage } from './PlanReviewPage'

const m = vi.hoisted(() => ({ listApprovals: vi.fn(), getApproval: vi.fn(), decide: vi.fn() }))
const role = vi.hoisted(() => ({ value: 'editor' as string | null }))
vi.mock('./useMyRole', () => ({ useMyRole: () => role.value }))
vi.mock('./aiApi', () => ({ aiApi: m }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const RUN = '22222222-aaaa-bbbb'
const mk = (o: Record<string, unknown> = {}) => ({
  id: 'a1', run_id: RUN, project_id: 'p', kind: 'A', subject: 'plan', payload: { plan: { entities: ['Invoice', 'Customer'], hooks: [], zones: [], dependencies: [] } },
  risk_flags: [], state: 'pending', requires_owner: false, bound_spec_hash: 'h', payload_hash: 'ph1', decided_at: null, decision_note: null, expires_at: '2099-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z', ...o,
})
let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); Object.values(m).forEach((f) => f.mockReset()); window.location.hash = ''; role.value = 'editor' })
async function mount() {
  window.location.hash = `#/p/p/plan?run=${RUN}`
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  await act(async () => { root!.render(createElement(PlanReviewPage, { projectId: 'p' })) })
  await act(async () => { await Promise.resolve() })
}
const q = (id: string) => host.querySelector(`[data-testid=${id}]`)
const click = async (el: Element | null) => { await act(async () => { (el as HTMLElement).click() }) }

describe('Plan review', () => {
  const same = () => m.getApproval.mockImplementation(async () => mk())
  it('approves an unedited plan without a plan in the body', async () => {
    m.listApprovals.mockResolvedValue([mk()]); same()
    await mount()
    m.decide.mockResolvedValue(mk({ state: 'approved' }))
    await click(q('plan-approve'))
    expect(m.decide).toHaveBeenCalledWith('p', 'a1', true, '', undefined, expect.objectContaining({ payload_hash: 'ph1' }))
  })
  it('approves an edited plan by sending it in the decision', async () => {
    m.listApprovals.mockResolvedValue([mk()]); same()
    await mount()
    await click(host.querySelector('tbody button'))
    expect(q('plan-approve')?.textContent).toContain('edited plan')
    m.decide.mockResolvedValue(mk({ state: 'approved' }))
    await click(q('plan-approve'))
    expect(m.decide).toHaveBeenCalledWith('p', 'a1', true, '', { entities: ['Customer'], hooks: [], zones: [], dependencies: [] }, expect.objectContaining({ payload_hash: 'ph1' }))
    expect(q('plan-done')?.textContent).toContain('edited plan was approved')
  })
  it('explains 422 plan_empty', async () => {
    m.listApprovals.mockResolvedValue([mk({ payload: { plan: { entities: ['Invoice'] } } })]); m.getApproval.mockImplementation(async () => mk({ payload: { plan: { entities: ['Invoice'] } } }))
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
  it('S3-003: an expired plan cannot be approved and says why', async () => {
    m.listApprovals.mockResolvedValue([mk({ expires_at: '2020-01-01T00:00:00Z' })])
    await mount()
    expect(q('plan-state')?.getAttribute('data-state')).toBe('expired')
    expect(q('plan-state')?.textContent).toContain('can no longer be approved')
    expect(q('plan-approve')).toBeNull()
    expect(q('plan-deny')).toBeNull()
  })
  it('S3-003: a viewer sees the plan read-only with the reason', async () => {
    role.value = 'viewer'
    m.listApprovals.mockResolvedValue([mk()])
    await mount()
    expect(q('plan-table')).not.toBeNull()
    expect(q('plan-gate-reason')?.textContent).toContain('Viewers')
    expect(q('plan-approve')).toBeNull() // no decision controls at all
    expect(q('plan-deny')).toBeNull()
    expect(host.querySelector('tbody button')).toBeNull() // no Remove
    expect(m.decide).not.toHaveBeenCalled()
  })
  it('S3-003: an editor cannot decide an owner-only plan', async () => {
    m.listApprovals.mockResolvedValue([mk({ requires_owner: true })])
    await mount()
    expect(q('plan-gate-reason')?.textContent).toContain('project owner')
    expect(q('plan-approve')).toBeNull()
    expect(m.decide).not.toHaveBeenCalled()
  })
  it('S3-005: a plan that changed after it was shown is not approved; the new plan is shown', async () => {
    m.listApprovals.mockResolvedValue([mk()])
    m.getApproval.mockResolvedValue(mk({ payload: { plan: { entities: ['Invoice', 'Customer', 'Secrets'], hooks: [], zones: [], dependencies: [] } } }))
    await mount()
    await click(q('plan-approve'))
    expect(m.decide).not.toHaveBeenCalled()
    expect(q('plan-changed')).not.toBeNull()
    expect(q('plan-table')?.textContent).toContain('Secrets')
  })
  it('409 run_finished is explained on the plan page', async () => {
    m.listApprovals.mockResolvedValue([mk()]); same()
    await mount()
    m.decide.mockRejectedValue(new ApiError(409, { code: 'run_finished', message: 'the run is already cancelled', details: [] }))
    await click(q('plan-approve'))
    expect(host.querySelector('[role=alert]')?.textContent).toContain('run has already finished')
    expect(q('plan-done')).toBeNull()
  })
})
