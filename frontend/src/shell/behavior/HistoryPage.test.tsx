import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { click, flush, mount, q, qa } from '../ai/testUtils'
import { HistoryPage } from './HistoryPage'

const m = vi.hoisted(() => ({
  put: vi.fn(),
  issues: vi.fn(),
}))
vi.mock('../../api/client', () => ({
  api: {
    getHistory: async () => ({ version: 3, history: [{ entity: 'Ticket', fields: ['title'], retention_days: 30, view_roles: ['admin'] }] }),
    putHistory: (...a: unknown[]) => m.put(...a),
    getBehaviorIssues: () => m.issues(),
    listEntities: async () => ({ items: [{ id: 'e1', name: 'Ticket' }, { id: 'e2', name: 'Note' }], total: 2 }),
    getStateMachines: async () => ({ state_machines: [{ entity: 'Ticket', field: 'status' }] }),
    listFields: async () => ({ items: [{ name: 'title' }, { name: 'status' }, { name: 'api_secret' }] }),
  },
  ApiError: class ApiError extends Error {
    status: number
    constructor(status = 0, message = 'api error') { super(message); this.status = status }
  },
}))

describe('HistoryPage wiring', () => {
  it('loads, edits, saves and shows a backend issue next to its field; state/secret fields are disabled', async () => {
    m.issues.mockResolvedValue({ issues: [] })
    m.put.mockImplementation(async (_id: string, items: unknown[], v: number) => ({ version: v + 1, history: items }))
    await mount(createElement(HistoryPage, { projectId: 'p' }))
    await flush()
    expect(qa('history-row')).toHaveLength(1)
    const box = (name: string) => [...document.querySelectorAll('input[type=checkbox]')].find((c) => c.nextElementSibling?.textContent === name) as HTMLInputElement
    expect(box('title').checked).toBe(true)
    expect(box('status').disabled).toBe(true) // state field
    expect(box('api_secret').disabled).toBe(true) // looks secret
    await click(box('status').parentElement!.parentElement!.querySelectorAll('input')[0] as HTMLInputElement) // title unchecked
    expect(box('title').checked).toBe(false)
    m.issues.mockResolvedValue({ issues: [{ code: 'x', severity: 'error', path: 'history[0].fields[0]', message: 'Pick at least one field' }] })
    const save = [...document.querySelectorAll('button')].find((b) => /save/i.test(b.textContent ?? '')) as HTMLButtonElement
    await click(save)
    await flush()
    expect(m.put).toHaveBeenCalledWith('p', [{ entity: 'Ticket', fields: [], retention_days: 30, view_roles: ['admin'] }], 3)
    expect(q('save-note')!.textContent).toBe('Saved (version 4).')
    expect(q('issue-summary')).not.toBeNull()
  })

  it('a 409 on save shows the conflict banner', async () => {
    const { ApiError } = await import('../../api/client')
    m.issues.mockResolvedValue({ issues: [] })
    m.put.mockRejectedValue(new (ApiError as unknown as new (s: number) => Error)(409))
    await mount(createElement(HistoryPage, { projectId: 'p' }))
    await flush()
    const box = document.querySelector('input[type=checkbox]') as HTMLInputElement
    await click(box)
    const save = [...document.querySelectorAll('button')].find((b) => /save/i.test(b.textContent ?? '')) as HTMLButtonElement
    await click(save)
    await flush()
    expect(q('conflict')).not.toBeNull()
  })
})
