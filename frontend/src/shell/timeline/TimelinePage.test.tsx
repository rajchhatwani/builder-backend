import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SpecOp } from '../../api/types'
import { TimelinePage } from './TimelinePage'

const m = vi.hoisted(() => ({
  list: vi.fn(), restore: vi.fn(), undo: vi.fn(), redo: vi.fn(), confirm: vi.fn(), toast: vi.fn(),
}))
vi.mock('../../api/client', () => ({
  api: { listSpecOps: m.list, restoreSpec: m.restore, undoSpec: m.undo, redoSpec: m.redo },
}))
vi.mock('../../components/Ui', () => ({ useUi: () => ({ confirm: m.confirm, toast: m.toast }) }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const op = (seq: number, t: string, payload: Record<string, unknown>): SpecOp => ({
  id: `i${seq}`, project_id: 'p', seq, op_type: t, origin: 'do', ref_seq: null,
  actor: { kind: 'user', user_id: 'u', email: 'maya@example.com' }, payload, inverse: { op_type: 'x', payload: {} },
  spec_hash_before: 'a', spec_hash_after: 'b', created_at: '2026-01-01T10:00:00Z',
})
const LOG = [op(2, 'add_field', { entity: 'Invoice', field: { name: 'total' } }), op(1, 'add_entity', { entity: { name: 'Invoice' } })]
const page = (items: SpecOp[]) => ({ items, total: items.length, limit: 200, offset: 0 })

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(TimelinePage, { projectId: 'p' })) })
  await act(async () => { await Promise.resolve() })
}
const byText = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const click = async (el: Element) => { await act(async () => { (el as HTMLElement).click() }) }

afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null; Object.values(m).forEach((f) => f.mockReset()) })

describe('TimelinePage', () => {
  it('shows an empty state with no operations', async () => {
    m.list.mockResolvedValue(page([]))
    await mount()
    expect(host.querySelector('[data-testid=timeline-empty]')).not.toBeNull()
  })

  it('shows a retryable error when the log cannot be loaded', async () => {
    m.list.mockRejectedValueOnce(new Error('boom')).mockResolvedValue(page(LOG))
    await mount()
    expect(host.querySelector('[role=alert]')?.textContent).toContain('boom')
    await click(byText(/Try again/))
    expect(host.querySelector('[data-testid=timeline-list]')).not.toBeNull()
  })

  it('lists operations with actor and summary, and previews a restore', async () => {
    m.list.mockResolvedValue(page(LOG))
    await mount()
    expect(host.textContent).toContain('Added field Invoice.total')
    expect(host.textContent).toContain('maya@example.com')
    await click(byText(/Version 1:/))
    expect(host.querySelector('[data-testid=timeline-impact]')?.textContent).toContain('1 change: 1 added field')
    expect(byText(/Restore the draft/).disabled).toBe(false)
  })

  it('does not offer restore for the current version', async () => {
    m.list.mockResolvedValue(page(LOG))
    await mount()
    await click(byText(/Version 2:/))
    expect(byText(/Already at this version/).disabled).toBe(true)
  })

  it('restores only after confirmation', async () => {
    m.list.mockResolvedValue(page(LOG))
    m.confirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true)
    m.restore.mockResolvedValue(op(3, 'replace_spec', {}))
    await mount()
    await click(byText(/Version 1:/))
    await click(byText(/Restore the draft/))
    expect(m.confirm).toHaveBeenCalledTimes(1)
    expect(m.confirm.mock.calls[0][0].title).toContain('version 1')
    expect(m.restore).not.toHaveBeenCalled()
    await click(byText(/Restore the draft/))
    expect(m.restore).toHaveBeenCalledWith('p', 1)
    expect(m.list).toHaveBeenCalledTimes(2) // reloaded after the restore
  })

  it('on 409 spec_conflict reloads the log and tells the user', async () => {
    m.list.mockResolvedValue(page(LOG))
    m.confirm.mockResolvedValue(true)
    m.restore.mockRejectedValue(Object.assign(new Error('conflict'), { status: 409, code: 'spec_conflict' }))
    await mount()
    await click(byText(/Version 1:/))
    await click(byText(/Restore the draft/))
    expect(m.list).toHaveBeenCalledTimes(2)
    expect(host.querySelector('[data-testid=timeline-alert]')?.textContent).toMatch(/Someone else changed/)
    expect(host.querySelector('[data-testid=timeline-preview]')).toBeNull() // selection cleared
  })
})
