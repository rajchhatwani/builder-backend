import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { ApprovalsPage } from './ApprovalsPage'
import { ProvenanceBadge } from './Provenance'

const m = vi.hoisted(() => ({ listApprovals: vi.fn(), getApproval: vi.fn(), decide: vi.fn() }))
const role = vi.hoisted(() => ({ value: 'editor' as string | null }))
vi.mock('./aiApi', () => ({ aiApi: m }))
vi.mock('./useMyRole', () => ({ useMyRole: () => role.value }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const future = new Date(Date.now() + 3_600_000 * 24).toISOString()
const mk = (o: Record<string, unknown> = {}) => ({
  id: '11111111-aaaa-bbbb', run_id: '22222222-aaaa-bbbb', project_id: 'p', kind: 'C', subject: 'review the finished change',
  payload: { summary: 'Added invoices', final: true, gate_report_hash: 'deadbeefdeadbeef', hooks: [{ name: 'on_save', author: 'ai' }], files: ['hooks/on_save.py'] },
  risk_flags: ['money'], state: 'pending', requires_owner: false, bound_spec_hash: 'h', payload_hash: 'ph1', decided_at: null, decision_note: null, expires_at: future, created_at: future, ...o,
})

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); Object.values(m).forEach((f) => f.mockReset()); window.location.hash = ''; role.value = 'editor' })
async function mount() {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  await act(async () => { root!.render(createElement(ApprovalsPage, { projectId: 'p' })) })
  await act(async () => { await Promise.resolve() })
}
const click = async (el: Element | null) => { await act(async () => { (el as HTMLElement).click() }) }
const type = async (el: Element | null, v: string) => {
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    set.call(el, v); el!.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const q = (id: string) => host.querySelector(`[data-testid=${id}]`)

describe('Approvals inbox', () => {
  it('lists pending approvals with kind, risk, expiry and owner badge, linking Gate A to the plan page', async () => {
    m.listApprovals.mockResolvedValue([mk({ kind: 'D', requires_owner: true }), mk({ id: '33333333-aaaa-bbbb', kind: 'A', risk_flags: [] })])
    await mount()
    expect(m.listApprovals).toHaveBeenCalledWith('p', { state: 'pending' })
    const rows = host.querySelectorAll('[data-testid=approval-row]')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('Risky change')
    expect(rows[0].querySelector('[data-testid=owner-badge]')).not.toBeNull()
    expect(rows[0].textContent).toMatch(/Expires in 2[34] h/)
    expect(rows[0].querySelector('[data-flag=money]')).not.toBeNull()
    expect(rows[1].querySelector('[data-testid=row-open]')?.getAttribute('href')).toBe('#/p/p/plan?run=22222222-aaaa-bbbb')
    expect(rows[0].querySelector('[data-testid=row-open]')?.getAttribute('href')).toBe('#/p/p/approvals?approval=11111111-aaaa-bbbb')
  })
  it('puts expired approvals in the decided tab', async () => {
    m.listApprovals.mockResolvedValue([mk({ expires_at: '2020-01-01T00:00:00Z' }), mk({ id: '4', state: 'approved' })])
    await mount()
    expect(q('approvals-empty')).not.toBeNull()
    await click(q('tab-decided'))
    expect(host.querySelectorAll('[data-testid=approval-row]')).toHaveLength(2)
  })
})

describe('Review screen', () => {
  const open = async (a: ReturnType<typeof mk>) => { window.location.hash = `#/p/p/approvals?approval=${a.id}`; m.getApproval.mockResolvedValue(a); await mount() }

  it('shows what is approved: summary, AI hook flagged, files, gate hash, risks, proposed overlay', async () => {
    await open(mk())
    expect(q('review-summary')?.textContent).toBe('Added invoices')
    expect(q('hook-row')?.getAttribute('data-ai')).toBe('true')
    expect(q('hook-row')?.querySelector('[data-testid=prov-ai]')).not.toBeNull()
    expect(q('review-files')?.textContent).toContain('hooks/on_save.py')
    expect(q('review-gates')?.textContent).toContain('deadbeefdead')
    expect(q('risk-flags')?.textContent).toContain('money')
    expect(q('proposed')).not.toBeNull()
  })
  it('fetches the approval by id and shows a structured spec diff with G0-G9 green', async () => {
    const a = mk({ payload: { summary: 's', gate_report_hash: 'deadbeefdeadbeef', gates_green: true, spec_diff: [{ section: 'entities', added: ['Invoice'], removed: ['Old'], changed: ['Customer'] }, { section: 'auth', changed: true }] } })
    await open(a)
    expect(m.getApproval).toHaveBeenCalledWith('p', a.id)
    expect(m.listApprovals).not.toHaveBeenCalled()
    const rows = host.querySelectorAll('[data-testid=diff-row]')
    expect(rows).toHaveLength(2)
    expect(rows[0].querySelector('[data-testid=diff-added]')?.textContent).toContain('Invoice')
    expect(rows[0].querySelector('[data-testid=diff-removed]')?.textContent).toContain('Old')
    expect(rows[0].querySelector('[data-testid=diff-changed]')?.textContent).toContain('Customer')
    expect(rows[1].textContent).toContain('auth changed')
    expect(q('gates-green')?.textContent).toContain('G0-G9 green')
    expect(q('review-gates')?.textContent).toContain('deadbeefdead')
  })
  it('approves with the note and shows the result', async () => {
    const a = mk()
    await open(a)
    m.decide.mockResolvedValue({ ...a, state: 'approved' })
    await click(q('review-approve'))
    expect(m.decide).toHaveBeenCalledWith('p', a.id, true, '', undefined, expect.objectContaining({ payload_hash: 'ph1', bound_spec_hash: 'h' }))
    expect(q('review-done')?.textContent).toContain('Approved')
    expect(q('review-approve')).toBeNull()
  })
  it('requires a note to deny', async () => {
    const a = mk()
    await open(a)
    await click(q('review-deny'))
    expect(m.decide).not.toHaveBeenCalled()
    expect(q('note-help')?.textContent).toContain('Say why')
    m.decide.mockResolvedValue({ ...a, state: 'denied', decision_note: 'too broad' })
    await type(q('review-note'), 'too broad')
    await click(q('review-deny'))
    expect(m.decide).toHaveBeenCalledWith('p', a.id, false, 'too broad', undefined, expect.objectContaining({ payload_hash: 'ph1' }))
  })
  it('disables both buttons with an explanation for a non-owner on an owner-only request', async () => {
    role.value = 'editor'
    await open(mk({ kind: 'D', requires_owner: true, payload: { op_type: 'remove_entity', name: 'Invoice' } }))
    expect((q('review-approve') as HTMLButtonElement).disabled).toBe(true)
    expect(q('gate-reason')?.textContent).toContain('owner')
    expect(q('review-approve')?.getAttribute('aria-describedby')).toBe('gate-reason')
    await click(q('review-approve'))
    expect(m.decide).not.toHaveBeenCalled()
  })
  it('lets an owner decide the same request', async () => {
    role.value = 'owner'
    await open(mk({ kind: 'D', requires_owner: true, payload: { op_type: 'remove_entity', name: 'Invoice' } }))
    expect((q('review-approve') as HTMLButtonElement).disabled).toBe(true) // until the name is typed
    await type(q('review-confirm'), 'Invoice')
    expect((q('review-approve') as HTMLButtonElement).disabled).toBe(false)
  })
  it('shows an expired request clearly and offers no decision', async () => {
    await open(mk({ expires_at: '2020-01-01T00:00:00Z' }))
    expect(q('review-state')?.getAttribute('data-state')).toBe('expired')
    expect(q('review-state')?.textContent).toContain('can no longer be approved')
    expect(q('review-approve')).toBeNull()
    expect(q('proposed')).toBeNull()
  })
  it('shows a superseded request as stale', async () => {
    await open(mk({ state: 'superseded' }))
    expect(q('review-state')?.textContent).toContain('newer request')
    expect(q('review-approve')).toBeNull()
  })
  it('shows the server error when the decision is refused', async () => {
    await open(mk())
    m.decide.mockRejectedValue(new Error('this approval has expired'))
    await click(q('review-approve'))
    expect(q('review-error')?.textContent).toContain('expired')
  })
})

describe('Review screen: bound to what was seen', () => {
  const ID2 = '99999999-aaaa-bbbb'
  const hashTo = async (id: string) => { await act(async () => { window.location.hash = `#/p/p/approvals?approval=${id}`; window.dispatchEvent(new HashChangeEvent('hashchange')) }) }

  it('S3-004: opening another approval clears the old screen, note and target', async () => {
    const a = mk(); const b = mk({ id: ID2, subject: 'second request' })
    window.location.hash = `#/p/p/approvals?approval=${a.id}`
    m.getApproval.mockResolvedValueOnce(a)
    await mount()
    await type(q('review-note'), 'old note')
    let release: (v: unknown) => void = () => undefined
    m.getApproval.mockReturnValueOnce(new Promise((r) => { release = r }))
    await hashTo(ID2)
    expect(q('review-approve')).toBeNull() // old approval is not decidable while the new one loads
    expect(host.textContent).not.toContain('review the finished change')
    await act(async () => { release(b) })
    expect((q('review-note') as HTMLInputElement).value).toBe('')
    m.getApproval.mockResolvedValue(b); m.decide.mockResolvedValue({ ...b, state: 'approved' })
    await click(q('review-approve'))
    expect(m.decide).toHaveBeenCalledWith('p', ID2, true, '', undefined, expect.objectContaining({ payload_hash: 'ph1' }))
  })
  it('S3-005: a request that changed since it was opened is not decided; the new one is shown', async () => {
    const a = mk()
    await (async () => { window.location.hash = `#/p/p/approvals?approval=${a.id}`; m.getApproval.mockResolvedValueOnce(a); await mount() })()
    m.getApproval.mockResolvedValueOnce(mk({ payload: { ...a.payload, summary: 'Added invoices AND dropped payments' } }))
    await click(q('review-approve'))
    expect(m.decide).not.toHaveBeenCalled()
    expect(q('review-changed')?.textContent).toContain('changed')
    expect(q('review-summary')?.textContent).toBe('Added invoices AND dropped payments')
  })
  it('S3-005: a server refusal as already decided reloads and says review again', async () => {
    const a = mk()
    window.location.hash = `#/p/p/approvals?approval=${a.id}`; m.getApproval.mockResolvedValue(a); await mount()
    m.decide.mockRejectedValue(new ApiError(409, { code: 'approval_already_decided', message: 'this approval is already denied', details: [] }))
    m.getApproval.mockResolvedValueOnce(a).mockResolvedValue({ ...a, state: 'denied', decision_note: 'nope' })
    await click(q('review-approve'))
    expect(q('review-error')?.textContent).toContain('already decided')
    expect(q('review-changed')).not.toBeNull()
    expect(q('review-state')?.getAttribute('data-state')).toBe('denied')
  })
  it('S3-004: a server 409 approval_changed reloads the card and says review again', async () => {
    const a = mk()
    window.location.hash = `#/p/p/approvals?approval=${a.id}`; m.getApproval.mockResolvedValue(a); await mount()
    m.decide.mockRejectedValue(new ApiError(409, { code: 'approval_changed', message: 'changed', details: [] }))
    m.getApproval.mockResolvedValueOnce(a).mockResolvedValue({ ...a, payload_hash: 'ph2', payload: { ...a.payload, summary: 'new' } })
    await click(q('review-approve'))
    expect(q('review-error')?.textContent).toContain('changed')
    expect(q('review-changed')).not.toBeNull()
    expect(q('review-summary')?.textContent).toBe('new')
  })
  it('409 run_finished is explained and the card is reloaded', async () => {
    const a = mk()
    window.location.hash = `#/p/p/approvals?approval=${a.id}`; m.getApproval.mockResolvedValue(a); await mount()
    m.decide.mockRejectedValue(new ApiError(409, { code: 'run_finished', message: 'the run is already cancelled', details: [] }))
    await click(q('review-approve'))
    expect(q('review-error')?.textContent).toContain('run has already finished')
    expect(q('review-done')).toBeNull()
  })
  it('C-005: Gate D shows the change and keeps Approve disabled until the name is typed', async () => {
    role.value = 'owner'
    const a = mk({ kind: 'D', requires_owner: true, risk_flags: ['data_deletion'], payload: { op_type: 'remove_entity', name: 'Invoice', run_id: 'r' } })
    window.location.hash = `#/p/p/approvals?approval=${a.id}`; m.getApproval.mockResolvedValue(a); await mount()
    expect(q('gate-d-headline')?.textContent).toBe('Remove the entity Invoice')
    expect(q('gate-d-rows')?.textContent).toContain('Invoice')
    expect((q('review-approve') as HTMLButtonElement).disabled).toBe(true)
    await type(q('review-confirm'), 'Invoic')
    expect((q('review-approve') as HTMLButtonElement).disabled).toBe(true)
    await type(q('review-confirm'), 'Invoice')
    expect((q('review-approve') as HTMLButtonElement).disabled).toBe(false)
    m.decide.mockResolvedValue({ ...a, state: 'approved' })
    await click(q('review-approve'))
    expect(m.decide).toHaveBeenCalledWith('p', a.id, true, '', undefined, expect.objectContaining({ payload_hash: 'ph1', bound_spec_hash: 'h' }))
  })
  it('Gate D: Deny never needs the confirmation text', async () => {
    role.value = 'owner'
    const a = mk({ kind: 'D', requires_owner: true, payload: { op_type: 'remove_entity', name: 'Invoice' } })
    window.location.hash = `#/p/p/approvals?approval=${a.id}`; m.getApproval.mockResolvedValue(a); await mount()
    await type(q('review-note'), 'too risky')
    m.decide.mockResolvedValue({ ...a, state: 'denied' })
    await click(q('review-deny'))
    expect(m.decide).toHaveBeenCalledWith('p', a.id, false, 'too risky', undefined, expect.objectContaining({ payload_hash: 'ph1' }))
  })
})

describe('Inbox robustness', () => {
  it('S3-006: a slow response for the old tab does not overwrite the newer tab', async () => {
    let slow: (v: unknown) => void = () => undefined
    m.listApprovals.mockReturnValueOnce(new Promise((r) => { slow = r }))
    await mount()
    m.listApprovals.mockResolvedValueOnce([mk({ id: '4', state: 'approved', subject: 'decided one' })])
    await click(q('tab-decided'))
    await act(async () => { slow([mk({ subject: 'late pending one' })]) })
    expect(host.textContent).toContain('decided one')
    expect(host.textContent).not.toContain('late pending one')
  })
  it('S3-006: accepts a paginated envelope, unknown kinds and rows without payload', async () => {
    m.listApprovals.mockResolvedValue({ items: [mk({ kind: 'Z', payload: null, risk_flags: null }), { junk: true }], total: 2 })
    await mount()
    const rows = host.querySelectorAll('[data-testid=approval-row]')
    expect(rows).toHaveLength(1)
    expect(rows[0].textContent).toContain('Gate Z')
  })
  it('S3-006: an empty or unexpected body is an empty inbox, not a crash', async () => {
    m.listApprovals.mockResolvedValue({ detail: 'x' })
    await mount()
    expect(q('approvals-empty')).not.toBeNull()
  })
})

describe('ProvenanceBadge', () => {
  it('marks AI with a run link and people as human', () => {
    host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
    act(() => { root!.render(createElement('div', null, createElement(ProvenanceBadge, { author: 'ai', projectId: 'p', runId: 'abcdef123456' }), createElement(ProvenanceBadge, { author: 'human' }))) })
    expect(q('prov-ai')?.textContent).toContain('AI')
    expect(q('prov-run-link')?.getAttribute('href')).toBe('#/p/p/build?run=abcdef123456')
    expect(q('prov-human')?.textContent).toBe('Human')
  })
  it('S3-014: the inbox tablist has roving tabindex and arrow keys', async () => {
    m.listApprovals.mockResolvedValue([])
    await mount()
    const p = q('tab-pending') as HTMLElement; const d = q('tab-decided') as HTMLElement
    expect([p.tabIndex, d.tabIndex]).toEqual([0, -1])
    await act(async () => { p.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) })
    expect(d.getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(d)
  })
  it('S3-014/S3-007: a failed decision moves focus to the error and shows the server code', async () => {
    window.location.hash = '#/approvals?approval=11111111-aaaa-bbbb'
    m.getApproval.mockResolvedValue(mk())
    m.decide.mockRejectedValue(new ApiError(500, { code: 'boom_code', message: 'It broke', details: [] }))
    await mount()
    await click(q('review-approve'))
    await act(async () => { await Promise.resolve() })
    expect(q('review-error')?.textContent).toBe('It broke (boom_code)')
    expect(document.activeElement).toBe(q('review-error'))
  })
})
