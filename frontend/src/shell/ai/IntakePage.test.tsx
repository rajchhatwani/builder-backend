import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IntakePage } from './IntakePage'

const m = vi.hoisted(() => ({ getRequirements: vi.fn(), intake: vi.fn(), answer: vi.fn(), putItem: vi.fn(), startRun: vi.fn() }))
vi.mock('./aiApi', () => ({ aiApi: m }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const MAP = {
  id: 'm', status: 'ready', sources: [],
  items: [
    { id: '1', kind: 'rule', text: '<b>Managers approve</b>', source_doc: 'spec.pdf', source_page: 2, source_section: null, status: 'open', covered_by: null },
    { id: '2', kind: 'entity', text: 'Leave request', source_doc: null, source_page: null, source_section: null, status: 'covered', covered_by: ['LeaveRequest'] },
  ],
  questions: [{ id: 'q1', text: 'Carry over days?', assumption: 'No carry over', answer: null, state: 'open' }],
}

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); Object.values(m).forEach((f) => f.mockReset()) })
async function mount() {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  await act(async () => { root!.render(createElement(IntakePage, { projectId: 'p' })) })
  await act(async () => { await Promise.resolve() })
}
const click = async (el: Element | null) => { await act(async () => { (el as HTMLElement).click() }) }

describe('IntakePage', () => {
  it('shows the map as plain text, grouped, and asks to confirm assumptions before starting', async () => {
    m.getRequirements.mockResolvedValue(MAP)
    m.startRun.mockResolvedValue({ id: 'r1' })
    await mount()
    expect(host.querySelectorAll('[data-testid=req-group]')).toHaveLength(2)
    expect(host.querySelector('b')).toBeNull() // no HTML injection
    expect(host.textContent).toContain('<b>Managers approve</b>')
    expect(host.textContent).toContain('From spec.pdf, page 2')
    expect(host.querySelector('[data-testid=coverage-summary]')?.textContent).toContain('1 of 2')
    await click(host.querySelector('[data-testid=start-build]'))
    expect(m.startRun).not.toHaveBeenCalled()
    expect(host.querySelector('[data-testid=confirm-assumptions]')).not.toBeNull()
    await click([...host.querySelectorAll('button')].find((b) => b.textContent?.startsWith('Accept assumptions and start')) ?? null)
    expect(m.startRun).toHaveBeenCalledWith('p', true)
  })
  it('starts straight away when no question is open', async () => {
    m.getRequirements.mockResolvedValue({ ...MAP, questions: [] })
    m.startRun.mockResolvedValue({ id: 'r1' })
    await mount()
    await click(host.querySelector('[data-testid=start-build]'))
    expect(m.startRun).toHaveBeenCalledWith('p', false)
  })
  it('marks an item out of scope', async () => {
    m.getRequirements.mockResolvedValue(MAP)
    m.putItem.mockResolvedValue(MAP)
    await mount()
    await click([...host.querySelectorAll('button')].find((b) => b.textContent === 'Mark out of scope') ?? null)
    expect(m.putItem).toHaveBeenCalledWith('p', { id: '2', text: 'Leave request', status: 'out_of_scope' })
  })
  it('accepts an item as a gap (unmet)', async () => {
    m.getRequirements.mockResolvedValue(MAP)
    m.putItem.mockResolvedValue(MAP)
    await mount()
    await click(host.querySelector('[data-testid=req-unmet]'))
    expect(m.putItem).toHaveBeenCalledWith('p', { id: '2', text: 'Leave request', status: 'unmet' })
  })
})
