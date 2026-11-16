import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { useSection, type SectionConfig } from './useSection'
import { useSpecBlocks } from '../connect/useSpecBlocks'

const specs: Record<string, () => Promise<unknown>> = {}
vi.mock('../../api/client', () => ({
  api: {
    getBehaviorIssues: async () => ({ issues: [] }),
    getSpecBlocks: (id: string) => specs[id](),
    validateProject: async () => ({ issues: [] }),
  },
  ApiError: class ApiError extends Error {},
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Item = { k: string }
const defer = <T,>() => {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

describe('stale loads', () => {
  it('useSection: an older project load landing last does not overwrite the newer one', async () => {
    const loads: Record<string, ReturnType<typeof defer<{ version: number; items: Item[] }>>> = { a: defer(), b: defer() }
    const cfg: SectionConfig<Item, Item> = {
      key: 'settings', check: () => ({}), load: (id) => loads[id].promise, save: async () => ({ version: 0, items: [] }),
      fromBody: (b) => b, toBody: (r) => r,
    }
    let st!: ReturnType<typeof useSection<Item, Item>>
    function Probe({ id }: { id: string }) { st = useSection(id, cfg); return null }
    const root = createRoot(document.createElement('div'))
    await act(async () => root.render(createElement(Probe, { id: 'a' })))
    await act(async () => root.render(createElement(Probe, { id: 'b' })))
    await act(async () => loads.b.resolve({ version: 2, items: [{ k: 'B' }] }))
    await act(async () => loads.a.resolve({ version: 1, items: [{ k: 'A' }] }))
    expect(st.state.version).toBe(2)
    expect(st.state.rows).toEqual([{ k: 'B' }])
  })

  it('useSpecBlocks: switching project drops the old spec to loading', async () => {
    const d = defer<unknown>()
    specs.a = async () => ({ marker: 'A' })
    specs.b = () => d.promise
    let out!: ReturnType<typeof useSpecBlocks>
    function Probe({ id }: { id: string }) { out = useSpecBlocks(id); return null }
    const root = createRoot(document.createElement('div'))
    await act(async () => root.render(createElement(Probe, { id: 'a' })))
    expect(out.load.status).toBe('ready')
    await act(async () => root.render(createElement(Probe, { id: 'b' })))
    expect(out.load.status).toBe('loading')
    await act(async () => d.resolve({ marker: 'B' }))
    expect(out.load.status).toBe('ready')
  })
})
