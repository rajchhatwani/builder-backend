import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AccessDiff } from '../../api/types'
import { AccessPage } from './AccessPage'
import { MATRIX } from './accessLogic.test'

const m = vi.hoisted(() => ({ matrix: vi.fn(), spec: vi.fn(), diff: vi.fn(), apply: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  api: { getAccessMatrix: m.matrix, getSpecJson: m.spec, diffAccess: m.diff, applySpecOp: m.apply },
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const SPEC = { auth: { permissions: [{ entity: 'Invoice', operation: 'list', roles: ['admin'] }] }, authorization: { field_access: [] } }
const DIFF: AccessDiff = {
  changes: [{ layer: 'object', entity: 'Invoice', target: 'list', role: 'clerk', before: 'no', after: 'yes', effect: 'gain' }],
  roles_gaining: { clerk: ['Invoice.list'] },
  roles_losing: {},
  weakens: false,
  counts: { gain: 1, lose: 0, change: 0, added: 0, removed: 0 },
}

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(AccessPage, { projectId: 'p' })) })
  await act(async () => { await Promise.resolve() })
}
const q = (s: string) => host.querySelector(s) as HTMLElement | null
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const tick = (fn: () => void) => act(async () => { fn(); await Promise.resolve() })
const box = (name: RegExp) => [...host.querySelectorAll('input[type=checkbox]')].find((i) => name.test(i.closest('label')?.textContent ?? ''))! as HTMLInputElement

afterEach(() => {
  act(() => root?.unmount()); host?.remove(); root = null
  Object.values(m).forEach((f) => f.mockReset())
})

describe('AccessPage', () => {
  it('renders the matrix as an accessible table', async () => {
    m.matrix.mockResolvedValue(MATRIX); m.spec.mockResolvedValue(SPEC)
    await mount()
    expect(q('caption')?.textContent).toContain('Object access for Invoice')
    expect([...host.querySelectorAll('thead th')].map((t) => t.textContent)).toEqual(['Role', 'list', 'update'])
    expect(host.querySelectorAll('tbody th[scope=row]')).toHaveLength(3)
    const clerk = [...host.querySelectorAll('tbody tr')][1]
    expect(clerk.textContent).toBe('clerkyesno')
    await tick(() => btn(/^Row$/).click())
    expect(q('caption')?.textContent).toContain('Row access for Invoice')
    expect(q('tbody')?.textContent).toContain('own')
  })

  it('shows an empty state without entities', async () => {
    m.matrix.mockResolvedValue({ roles: ['(public)'], entities: [], cells: [] }); m.spec.mockResolvedValue(SPEC)
    await mount()
    expect(q('[data-testid=access-empty]')).not.toBeNull()
    expect(q('table')).toBeNull()
  })

  it('shows a retryable error', async () => {
    m.matrix.mockRejectedValueOnce(new Error('boom')); m.matrix.mockResolvedValue(MATRIX); m.spec.mockResolvedValue(SPEC)
    await mount()
    expect(q('[role=alert]')?.textContent).toContain('boom')
    await tick(() => btn(/Try again/).click())
    await act(async () => { await Promise.resolve() })
    expect(q('table')).not.toBeNull()
  })

  it('shows the diff before applying and applies without confirm when it does not weaken', async () => {
    m.matrix.mockResolvedValue(MATRIX); m.spec.mockResolvedValue(SPEC); m.diff.mockResolvedValue(DIFF); m.apply.mockResolvedValue({})
    await mount()
    await tick(() => box(/clerk/).click())
    await act(async () => { await Promise.resolve() })
    expect(m.diff).toHaveBeenCalledWith('p', { permissions: [{ entity: 'Invoice', operation: 'list', roles: ['admin', 'clerk'] }], field_access: null })
    expect(q('[data-testid=access-diff-lines]')?.textContent).toBe('Role clerk gains Invoice.list')
    expect(q('[data-testid=access-weakens]')).toBeNull()
    expect(m.apply).not.toHaveBeenCalled()
    expect(btn(/Apply change/)).toBeTruthy()
    await tick(() => btn(/Apply change/).click())
    await act(async () => { await Promise.resolve() })
    expect(m.apply).toHaveBeenCalledTimes(1)
    const [pid, op, payload, confirm] = m.apply.mock.calls[0]
    expect([pid, op, confirm]).toEqual(['p', 'replace_spec', false])
    expect((payload as { spec: { auth: { permissions: { roles: string[] }[] } } }).spec.auth.permissions[0].roles).toEqual(['admin', 'clerk'])
  })

  it('warns and sends confirm_weakening when the diff weakens', async () => {
    m.matrix.mockResolvedValue(MATRIX); m.spec.mockResolvedValue(SPEC); m.diff.mockResolvedValue({ ...DIFF, weakens: true }); m.apply.mockResolvedValue({})
    await mount()
    await tick(() => box(/clerk/).click())
    await act(async () => { await Promise.resolve() })
    expect(q('[data-testid=access-weakens]')?.textContent).toContain('more access')
    expect(m.apply).not.toHaveBeenCalled()
    await tick(() => btn(/Apply and confirm more access/).click())
    await act(async () => { await Promise.resolve() })
    expect(m.apply.mock.calls[0][3]).toBe(true)
  })

  it('edits a field rule through the field layer', async () => {
    m.matrix.mockResolvedValue(MATRIX); m.spec.mockResolvedValue(SPEC); m.diff.mockResolvedValue(DIFF)
    await mount()
    await tick(() => btn(/^Field$/).click())
    await tick(() => box(/No field rule[\s\S]*/).click())
    await act(async () => { await Promise.resolve() })
    expect(m.diff.mock.calls[0][1].field_access).toEqual([{ entity: 'Invoice', field: 'amount', read_roles: ['admin', 'clerk'], write_roles: null }])
    expect(m.diff.mock.calls[0][1].permissions).toBeNull()
  })
})
