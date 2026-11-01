import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { useSection, type SectionConfig } from './useSection'

vi.mock('../../api/client', () => ({
  api: { getBehaviorIssues: async () => ({ issues: [] }) },
  ApiError: class ApiError extends Error {
    status = 0
  },
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Item = { k: string }
// each fake section keeps its OWN version, like the backend
function fake(key: SectionConfig<Item, Item>['key'], start: number) {
  let version = start
  const saveSpy = vi.fn(async (_p: string, items: Item[], expected: number) => {
    if (expected !== version) throw new Error('409')
    version += 1
    return { version, items }
  })
  const cfg: SectionConfig<Item, Item> = {
    key, check: () => ({}), load: async () => ({ version, items: [] }), save: saveSpy,
    fromBody: (b) => b, toBody: (r) => r,
  }
  return { cfg, saveSpy }
}

describe('useSection: independent per-section versions', () => {
  it('saving one section leaves another section on its own version', async () => {
    const a = fake('settings', 1)
    const b = fake('sequences', 5)
    let hooks!: { a: ReturnType<typeof useSection<Item, Item>>; b: ReturnType<typeof useSection<Item, Item>> }
    function Probe() {
      hooks = { a: useSection('p', a.cfg), b: useSection('p', b.cfg) }
      return null
    }
    const root = createRoot(document.createElement('div'))
    await act(async () => root.render(createElement(Probe)))
    expect(hooks.a.state.version).toBe(1)
    expect(hooks.b.state.version).toBe(5)

    await act(async () => hooks.a.save())
    expect(hooks.a.state.version).toBe(2)
    expect(hooks.b.state.version).toBe(5)

    await act(async () => hooks.b.save())
    expect(b.saveSpy).toHaveBeenLastCalledWith('p', [], 5)
    expect(hooks.b.state.conflict).toBe(false)
    expect(hooks.b.state.version).toBe(6)
    await act(async () => root.unmount())
  })
})
