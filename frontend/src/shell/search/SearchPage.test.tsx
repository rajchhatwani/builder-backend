import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { click, mount, q, qa, setInput } from '../ai/testUtils'
import { SearchPage } from './SearchPage'

const m = vi.hoisted(() => ({ spec: vi.fn(), search: vi.fn(), reindex: vi.fn(), roles: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: { getSpecJson: m.spec, searchProject: m.search, reindexSearch: m.reindex, getBehaviorRoles: m.roles } }))
beforeEach(() => { Object.values(m).forEach((f) => f.mockReset()); m.spec.mockResolvedValue({ entities: [{ name: 'Invoice', fields: [] }] }); m.roles.mockResolvedValue({ roles: [{ name: 'admin', label: 'Admin' }, { name: 'clerk', label: 'Clerk' }] }) })

describe('SearchPage', () => {
  it('sends the chosen role as as_role', async () => {
    m.search.mockResolvedValue({ hits: [], total: 0 })
    await mount(createElement(SearchPage, { projectId: 'p' }))
    await setInput(q('search-role') as HTMLSelectElement, 'clerk')
    await setInput(q('search-input') as HTMLInputElement, 'acme')
    await click(q('search-run'))
    expect(m.search).toHaveBeenCalledWith('p', 'Invoice', 'acme', 20, 'clerk')
  })


  it('searches the chosen entity and lists hits', async () => {
    m.search.mockResolvedValue({ hits: [{ id: '1', title: 'Acme' }], total: 1 })
    await mount(createElement(SearchPage, { projectId: 'p' }))
    expect((q('search-run') as HTMLButtonElement).disabled).toBe(true)
    await setInput(q('search-input') as HTMLInputElement, 'acme')
    await click(q('search-run'))
    expect(m.search).toHaveBeenCalledWith('p', 'Invoice', 'acme', 20, undefined)
    expect(q('search-total')?.textContent).toBe('1 result')
    expect(qa('search-hit')[0].textContent).toBe('title: Acme')
  })

  it('shows a search error', async () => {
    m.search.mockRejectedValueOnce(new Error('unknown role'))
    await mount(createElement(SearchPage, { projectId: 'p' }))
    await setInput(q('search-input') as HTMLInputElement, 'x')
    await click(q('search-run'))
    expect(q('search-error')?.textContent).toBe('unknown role')
  })

  it('reindexes and shows the generic response, or its error', async () => {
    m.reindex.mockResolvedValueOnce({ indexed: 4 })
    await mount(createElement(SearchPage, { projectId: 'p' }))
    await click(q('search-reindex'))
    expect(m.reindex).toHaveBeenCalledWith('p')
    expect(q('search-reindex-result')?.textContent).toContain('"indexed": 4')
    m.reindex.mockRejectedValueOnce(new Error('not found'))
    await click(q('search-reindex'))
    expect(q('search-reindex-error')?.textContent).toBe('not found')
    expect(q('search-reindex-result')).toBeNull()
  })

  it('explains when there is no entity yet', async () => {
    m.spec.mockResolvedValue({ entities: [] })
    await mount(createElement(SearchPage, { projectId: 'p' }))
    expect(q('search-noentities')).not.toBeNull()
  })

  it('shows a load error with Try again, not the empty-entities state (F-1318)', async () => {
    m.spec.mockReset()
    m.spec.mockRejectedValueOnce(new Error('spec down')).mockResolvedValue({ entities: [{ name: 'Invoice', fields: [] }] })
    await mount(createElement(SearchPage, { projectId: 'p' }))
    expect(q('search-load-error')?.textContent).toContain('spec down')
    expect(q('search-noentities')).toBeNull()
    await click(q('search-retry'))
    expect(q('search-load-error')).toBeNull()
    expect(q('search-entity')).not.toBeNull()
  })
})
