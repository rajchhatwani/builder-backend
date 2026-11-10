import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CustomFieldsPage } from './CustomFieldsPage'

const m = vi.hoisted(() => ({ spec: vi.fn(), list: vi.fn(), define: vi.fn(), remove: vi.fn(), check: vi.fn(), promote: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  api: { getSpecJson: m.spec, listCustomFields: m.list, defineCustomField: m.define, removeCustomField: m.remove, checkPromoteCustomField: m.check, promoteCustomField: m.promote },
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const SPEC = { entities: [{ name: 'Contact', fields: [] }] }
const F = { name: 'score', type: 'int', required: false, max_length: null, enum_values: null }
const page = (items: unknown[]) => ({ entity: 'Contact', enabled: true, max_keys: 50, max_bytes: 8192, items })

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
const q = (s: string) => host.querySelector(s) as HTMLElement | null
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })
const click = async (re: RegExp) => { await act(async () => { btn(re).click() }); await flush() }
async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(CustomFieldsPage, { projectId: 'p' })) })
  await flush(); await flush()
}
async function type(el: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => { set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })) })
}

afterEach(() => {
  act(() => root?.unmount()); host?.remove(); root = null
  Object.values(m).forEach((f) => f.mockReset())
})

describe('CustomFieldsPage', () => {
  it('lists fields, defines a new one with labelled inputs', async () => {
    m.spec.mockResolvedValue(SPEC); m.list.mockResolvedValueOnce(page([])).mockResolvedValue(page([F]))
    m.define.mockResolvedValue(F)
    await mount()
    expect(q('[data-testid=cf-none]')).not.toBeNull()
    const input = q('input:not([type=checkbox])') as HTMLInputElement
    expect(host.querySelector(`label[for="${input.id}"]`)?.textContent).toBe('Field name')
    await type(input, 'score')
    await click(/Add field/)
    expect(m.define).toHaveBeenCalledWith('p', 'Contact', { name: 'score', type: 'string', required: false })
    expect(host.querySelectorAll('[data-testid=cf-row]').length).toBe(1)
  })

  it('checks before promoting and blocks promotion when the check fails', async () => {
    m.spec.mockResolvedValue(SPEC); m.list.mockResolvedValue(page([F]))
    m.check.mockResolvedValueOnce({ ok: false, problems: [{ code: 'x', message: 'value 3 is not a whole number', sample_index: 3, severity: 'error' }], plan_sql: [] })
    await mount()
    await click(/Check score for promotion/)
    expect(q('[data-testid=cf-check]')?.textContent).toContain('value 3 is not a whole number')
    expect((btn(/Promote score to a column/) as HTMLButtonElement).disabled).toBe(true)
    m.check.mockResolvedValueOnce({ ok: true, problems: [], plan_sql: ['ALTER TABLE contacts ADD COLUMN score integer'] })
    await click(/Check score for promotion/)
    expect(q('[data-testid=cf-check]')?.textContent).toContain('ALTER TABLE')
    m.promote.mockResolvedValue({ entity: 'Contact', name: 'score', op_seq: 7, plan_sql: [] })
    await click(/Promote score to a column/)
    expect(m.promote).toHaveBeenCalledWith('p', 'Contact', 'score')
    expect(q('[data-testid=cf-notice]')?.textContent).toContain('real column')
    expect(q('[data-testid=cf-check]')).toBeNull()
  })

  it('removes a field and shows API errors', async () => {
    m.spec.mockResolvedValue(SPEC); m.list.mockResolvedValue(page([F])); m.remove.mockRejectedValueOnce(new Error('nope'))
    await mount()
    await click(/Remove score/)
    expect(q('[data-testid=cf-error]')?.textContent).toContain('nope')
  })

  it('shows an empty state without entities', async () => {
    m.spec.mockResolvedValue({ entities: [] })
    await mount()
    expect(q('[data-testid=cf-empty]')).not.toBeNull()
  })
})
