import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { click, flush, mount, q, qa } from '../ai/testUtils'
import { SeedPage } from './SeedPage'

const m = vi.hoisted(() => ({ put: vi.fn(), issues: vi.fn(), entities: vi.fn() }))
vi.mock('../../api/client', () => ({
  api: {
    getSeed: async () => ({ version: 3, seed: [] }),
    putSeed: (...a: unknown[]) => m.put(...a),
    getBehaviorIssues: () => m.issues(),
    listEntities: () => m.entities(),
    listRelations: async () => ({ items: [], total: 0 }),
    getStateMachines: async () => ({ state_machines: [] }),
    listFields: async () => ({ items: [{ name: 'title', type: 'string', required: true, unique: false, default: null, max_length: 50, min_value: null, max_value: null, enum_values: null }], total: 1 }),
  },
  ApiError: class ApiError extends Error {
    status: number
    constructor(status = 0, message = 'api error') { super(message); this.status = status }
  },
}))

const button = (re: RegExp) => [...document.querySelectorAll('button')].find((b) => re.test(b.textContent ?? '')) as HTMLButtonElement

describe('SeedPage wiring', () => {
  it('adds a profile with the first free name, opens its form and removes it again', async () => {
    m.issues.mockResolvedValue({ issues: [] })
    m.entities.mockResolvedValue({ items: [{ id: 'e1', name: 'Ticket' }], total: 1 })
    await mount(createElement(SeedPage, { projectId: 'p' }))
    await flush()
    expect(q('seed-empty')).not.toBeNull()
    await click(button(/Add a profile/))
    expect(q('seed-empty')).toBeNull()
    expect(qa('seed-row')).toHaveLength(1)
    expect(q('seed-form')).not.toBeNull()
    expect((q('seed-form')!.querySelector('input') as HTMLInputElement).value).toBe('demo')
    await click(document.querySelector('[aria-label="Remove profile demo"]'))
    expect(qa('seed-row')).toHaveLength(0)
    expect(q('seed-empty')).not.toBeNull()
  })

  it('an entity catalog failure shows a retry instead of the page body', async () => {
    m.entities.mockRejectedValue(new Error('entities down'))
    await mount(createElement(SeedPage, { projectId: 'p' }))
    await flush()
    expect(document.body.textContent).toMatch(/entities down/)
    expect(qa('seed-row')).toHaveLength(0)
  })
})
