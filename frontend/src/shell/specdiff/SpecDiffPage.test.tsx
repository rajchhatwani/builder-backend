import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SpecDiffPage } from './SpecDiffPage'

const m = vi.hoisted(() => ({ spec: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: { getSpecJson: m.spec } }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const CURRENT = {
  entities: [
    { name: 'Invoice', fields: [{ name: 'amount', type: 'decimal' }] },
    { name: 'Order', fields: [] },
  ],
}
const BASELINE = { entities: [{ name: 'Invoice', fields: [{ name: 'amount', type: 'int' }] }, { name: 'Legacy', fields: [] }] }

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(SpecDiffPage, { projectId: 'p' })) })
  await act(async () => { await Promise.resolve() })
}
const q = (s: string) => host.querySelector(s) as HTMLElement | null
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const click = async (re: RegExp) => { await act(async () => { btn(re).click() }) }
async function paste(value: string) {
  const el = q('textarea') as HTMLTextAreaElement
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
  await act(async () => { set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })) })
}

beforeEach(() => {
  window.localStorage.clear()
  m.spec.mockReset()
  m.spec.mockResolvedValue(CURRENT)
})
afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  root = null
})

describe('SpecDiffPage', () => {
  it('asks for a baseline when there is none', async () => {
    await mount()
    expect(q('[data-testid=specdiff-nobaseline]')?.textContent).toContain('No baseline to compare with')
    expect(q('[data-testid=specdiff-source]')?.textContent).toBe('No baseline yet.')
  })

  it('shows added, removed and changed with text markers, not only color', async () => {
    await mount()
    await paste(JSON.stringify(BASELINE))
    await click(/Use as baseline/)
    const text = q('[data-testid=specdiff-result]')!.textContent!
    expect(q('[data-testid=specdiff-summary]')?.textContent).toContain('3 differences')
    expect(text).toContain('+ Added')
    expect(text).toContain('Order')
    expect(text).toContain('- Removed')
    expect(text).toContain('Legacy')
    expect(text).toContain('~ Changed')
    expect(text).toContain('~ field amount · type: int -> decimal')
  })

  it('says "No differences" right after a snapshot, and stores it per project', async () => {
    await mount()
    await click(/Save current spec as baseline/)
    expect(q('[data-testid=specdiff-empty]')?.textContent).toContain('No differences')
    expect(q('[data-testid=specdiff-source]')?.textContent).toMatch(/^Baseline: snapshot saved \d{4}-/)
    expect(window.localStorage.getItem('bb.specBaseline.p')).toContain('"savedAt"')
  })

  it('uses a stored snapshot on the next visit and clears it on request', async () => {
    window.localStorage.setItem('bb.specBaseline.p', JSON.stringify({ savedAt: '2026-11-09T10:00:00.000Z', spec: BASELINE }))
    await mount()
    expect(q('[data-testid=specdiff-source]')?.textContent).toBe('Baseline: snapshot saved 2026-11-09T10:00:00.000Z')
    expect(q('[data-testid=specdiff-result]')).not.toBeNull()
    await click(/Clear baseline/)
    expect(window.localStorage.getItem('bb.specBaseline.p')).toBeNull()
    expect(q('[data-testid=specdiff-nobaseline]')).not.toBeNull()
  })

  it('shows an error for invalid JSON and keeps the old result', async () => {
    await mount()
    await paste('{oops')
    await click(/Use as baseline/)
    expect(q('[data-testid=specdiff-error]')?.textContent).toContain('not valid JSON')
    expect(q('[data-testid=specdiff-nobaseline]')).not.toBeNull()
  })

  it('shows a retry when the spec cannot be loaded', async () => {
    m.spec.mockRejectedValueOnce(new Error('boom'))
    await mount()
    expect(q('[role=alert]')?.textContent).toContain('boom')
    await click(/Try again/)
    expect(q('[data-testid=specdiff-nobaseline]')).not.toBeNull()
  })
})
