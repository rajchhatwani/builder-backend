import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { SettingsPage } from './SettingsPage'

const m = vi.hoisted(() => ({ putSettings: vi.fn(), issues: vi.fn() }))
vi.mock('../../api/client', () => ({
  api: {
    getSettings: async () => ({ version: 4, settings: [{ key: 'vat_rate', type: 'decimal', default: '0.2', label: 'VAT', read_roles: [], edit_roles: ['admin'] }] }),
    getSequences: async () => ({ version: 1, sequences: [] }),
    getLists: async () => ({ version: 2, lists: [] }),
    putSettings: (...a: unknown[]) => m.putSettings(...a),
    getBehaviorIssues: () => m.issues(),
  },
  ApiError: class ApiError extends Error {
    status: number
    constructor(status = 0, message = 'api error') { super(message); this.status = status }
  },
}))

const button = (re: RegExp) => [...document.querySelectorAll('button')].find((b) => re.test(b.textContent ?? '')) as HTMLButtonElement

describe('SettingsPage wiring', () => {
  it('switches tabs, adds and removes a row, and saves with the loaded version', async () => {
    m.issues.mockResolvedValue({ issues: [] })
    m.putSettings.mockImplementation(async (_id: string, items: unknown[], v: number) => ({ version: v + 1, settings: items }))
    await mount(createElement(SettingsPage, { projectId: 'p' }))
    await flush()
    expect(qa('setting-row')).toHaveLength(1)
    await click(button(/^Sequences$/))
    expect(q('sequences-empty')).not.toBeNull()
    expect(qa('setting-row')).toHaveLength(0)
    await click(button(/^Lists$/))
    expect(q('lists-empty')).not.toBeNull()
    await click(button(/^Settings$/))
    expect(qa('setting-row')).toHaveLength(1)
    await click(button(/Add setting/))
    expect(qa('setting-row')).toHaveLength(2)
    await click(document.querySelector('[aria-label="Remove setting 2"]'))
    expect(qa('setting-row')).toHaveLength(1)
    await setInput(document.querySelector('fieldset input') as HTMLInputElement, 'tax_rate')
    await click(button(/save/i))
    await flush()
    expect(m.putSettings).toHaveBeenCalledTimes(1)
    const [pid, items, version] = m.putSettings.mock.calls[0]
    expect(pid).toBe('p')
    expect(version).toBe(4)
    expect((items as { key: string }[]).map((i) => i.key)).toEqual(['tax_rate'])
    expect(q('save-note')!.textContent).toBe('Saved (version 5).')
  })

  it('a backend issue lands next to its field', async () => {
    m.putSettings.mockImplementation(async (_id: string, items: unknown[], v: number) => ({ version: v + 1, settings: items }))
    m.issues.mockResolvedValue({ issues: [{ code: 'x', severity: 'error', path: 'settings[0].default', message: 'Default is out of range' }] })
    await mount(createElement(SettingsPage, { projectId: 'p' }))
    await flush()
    await setInput(document.querySelector('fieldset input') as HTMLInputElement, 'vat')
    await click(button(/save/i))
    await flush()
    expect(q('issue-summary')).not.toBeNull()
    expect(qa('field-error').some((e) => /out of range/.test(e.textContent ?? ''))).toBe(true)
  })
})
