import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { HooksPage } from './HooksPage'

const m = vi.hoisted(() => ({ put: vi.fn(), issues: vi.fn(), entities: vi.fn() }))
vi.mock('../../api/client', () => ({
  api: {
    getHooks: async () => ({ version: 7, hooks: [] }),
    putHooks: (...a: unknown[]) => m.put(...a),
    getBehaviorIssues: () => m.issues(),
    listEntities: () => m.entities(),
    getStateMachines: async () => ({ state_machines: [] }),
    listFields: async () => ({ items: [{ name: 'title', type: 'string' }], total: 1 }),
  },
  ApiError: class ApiError extends Error {
    status: number
    constructor(status = 0, message = 'api error') { super(message); this.status = status }
  },
}))

const button = (re: RegExp) => [...document.querySelectorAll('button')].find((b) => re.test(b.textContent ?? '')) as HTMLButtonElement

describe('HooksPage wiring', () => {
  it('declares a hook, opens its form, removes it again and shows the empty state', async () => {
    m.issues.mockResolvedValue({ issues: [] })
    m.entities.mockResolvedValue({ items: [{ id: 'e1', name: 'Ticket' }], total: 1 })
    await mount(createElement(HooksPage, { projectId: 'p' }))
    await flush()
    expect(q('hooks-empty')).not.toBeNull()
    await click(button(/Declare a hook/))
    expect(q('hooks-empty')).toBeNull()
    expect(qa('hook-row')).toHaveLength(1)
    expect(q('hook-form')).not.toBeNull()
    await click(document.querySelector('[aria-label="Remove hook New hook"]'))
    expect(qa('hook-row')).toHaveLength(0)
    expect(q('hooks-empty')).not.toBeNull()
  })

  it('saves a named hook with the loaded version', async () => {
    m.issues.mockResolvedValue({ issues: [] })
    m.entities.mockResolvedValue({ items: [{ id: 'e1', name: 'Ticket' }], total: 1 })
    m.put.mockImplementation(async (_id: string, items: unknown[], v: number) => ({ version: v + 1, hooks: items }))
    await mount(createElement(HooksPage, { projectId: 'p' }))
    await flush()
    await click(button(/Declare a hook/))
    await setInput(document.querySelector('[data-testid="hook-form"] input') as HTMLInputElement, 'check_total')
    await click(button(/save/i))
    await flush()
    expect(m.put).toHaveBeenCalledTimes(1)
    expect(m.put.mock.calls[0][0]).toBe('p')
    expect(m.put.mock.calls[0][2]).toBe(7)
    expect((m.put.mock.calls[0][1] as { name: string }[])[0].name).toBe('check_total')
  })

  it('an entity catalog failure shows a retry instead of the form', async () => {
    m.entities.mockRejectedValue(new Error('entities down'))
    await mount(createElement(HooksPage, { projectId: 'p' }))
    await flush()
    expect(document.body.textContent).toMatch(/entities down/)
    expect(button(/retry|try again/i)).toBeTruthy()
  })
})
