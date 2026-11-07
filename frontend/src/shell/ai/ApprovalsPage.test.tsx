import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
  risk_flags: ['money'], state: 'pending', requires_owner: false, bound_spec_hash: 'h', decided_at: null, decision_note: null, expires_at: future, created_at: future, ...o,
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
    expect(m.decide).toHaveBeenCalledWith('p', a.id, true, '')
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
    expect(m.decide).toHaveBeenCalledWith('p', a.id, false, 'too broad')
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
    await open(mk({ kind: 'D', requires_owner: true, payload: { op_type: 'remove_entity' } }))
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

describe('ProvenanceBadge', () => {
  it('marks AI with a run link and people as human', () => {
    host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
    act(() => { root!.render(createElement('div', null, createElement(ProvenanceBadge, { author: 'ai', projectId: 'p', runId: 'abcdef123456' }), createElement(ProvenanceBadge, { author: 'human' }))) })
    expect(q('prov-ai')?.textContent).toContain('AI')
    expect(q('prov-run-link')?.getAttribute('href')).toBe('#/p/p/build?run=abcdef123456')
    expect(q('prov-human')?.textContent).toBe('Human')
  })
})
