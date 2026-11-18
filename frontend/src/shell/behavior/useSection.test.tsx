import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { useSection, type SectionConfig } from './useSection'

vi.mock('../../api/client', () => ({
  api: { getBehaviorIssues: async () => ({ issues: [] }) },
  ApiError: class ApiError extends Error {
    status: number
    constructor(status = 0, message = 'api error') { super(message); this.status = status }
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

describe('useSection: edits during save and stale per-field messages', () => {
  it('F-0631: rows edited while a save is in flight stay dirty', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => { release = r })
    let version = 1
    const cfg: SectionConfig<Item, Item> = {
      key: 'settings', check: () => ({}), load: async () => ({ version, items: [{ k: 'a' }] }),
      save: async (_p, items) => { await gate; version += 1; return { version, items } },
      fromBody: (b) => b, toBody: (r) => r,
    }
    let h!: ReturnType<typeof useSection<Item, Item>>
    function Probe() {
      h = useSection('p', cfg)
      return null
    }
    const root = createRoot(document.createElement('div'))
    await act(async () => root.render(createElement(Probe)))
    let pending!: Promise<void>
    await act(async () => { pending = h.save() })
    await act(async () => h.change([{ k: 'newer' }], [0, 'k']))
    await act(async () => { release(); await pending })
    expect(h.state.dirty).toBe(true)
    expect(h.state.rows).toEqual([{ k: 'newer' }])
    await act(async () => root.unmount())
  })

  it('F-0633: editing fields clears indexed messages such as fields[2]', async () => {
    const cfg: SectionConfig<Item, Item> = {
      key: 'history', check: () => ({}), load: async () => ({ version: 1, items: [{ k: 'a' }] }),
      save: async (_p, items) => ({ version: 2, items }), fromBody: (b) => b, toBody: (r) => r,
      mapIssues: () => ({ section: [], rows: { 0: { fields: { 'fields[2]': ['bad'], other: ['keep'] } } } }) as never,
    }
    let h!: ReturnType<typeof useSection<Item, Item>>
    function Probe() {
      h = useSection('p', cfg)
      return null
    }
    const root = createRoot(document.createElement('div'))
    await act(async () => root.render(createElement(Probe)))
    expect(h.state.issues.rows[0].fields['fields[2]']).toBeTruthy()
    await act(async () => h.change([{ k: 'a' }], [0, 'fields']))
    expect(h.state.issues.rows[0].fields['fields[2]']).toBeUndefined()
    expect(h.state.issues.rows[0].fields.other).toEqual(['keep'])
    await act(async () => root.unmount())
  })
})

describe('useSection: conflict and stale issue indexes', () => {
  function probe(cfg: SectionConfig<Item, Item>) {
    const out = {} as { h: ReturnType<typeof useSection<Item, Item>> }
    function Probe() { out.h = useSection('p', cfg); return null }
    return { out, Probe }
  }

  it('F-1290: an ApiError 409 on save sets conflict (not a plain save error)', async () => {
    const cfg: SectionConfig<Item, Item> = {
      key: 'settings', check: () => ({}), load: async () => ({ version: 1, items: [{ k: 'a' }] }),
      save: async () => { throw new (ApiError as unknown as new (s: number) => Error)(409) },
      fromBody: (b) => b, toBody: (r) => r,
    }
    const { out, Probe } = probe(cfg)
    const root = createRoot(document.createElement('div'))
    await act(async () => root.render(createElement(Probe)))
    await act(async () => out.h.save())
    expect(out.h.state.conflict).toBe(true)
    expect(out.h.state.saveError).toBe('')
    expect(out.h.state.saving).toBe(false)
    await act(async () => root.unmount())
  })

  it('F-1293: issues fetched after a save do not land on shifted rows when rows were removed meanwhile', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => { release = r })
    let afterSave = false
    const cfg: SectionConfig<Item, Item> = {
      key: 'settings', check: () => ({}), load: async () => ({ version: 1, items: [{ k: 'a' }, { k: 'b' }] }),
      save: async (_p, items) => { await gate; afterSave = true; return { version: 2, items } },
      fromBody: (b) => b, toBody: (r) => r,
      mapIssues: () => (afterSave ? { section: [], rows: { 0: { row: [], fields: { k: ['bad'] } } } } : { section: [], rows: {} }) as never,
    }
    const { out, Probe } = probe(cfg)
    const root = createRoot(document.createElement('div'))
    await act(async () => root.render(createElement(Probe)))
    let pending!: Promise<void>
    await act(async () => { pending = out.h.save() })
    await act(async () => out.h.change([{ k: 'b' }])) // remove row 0 while saving
    await act(async () => { release(); await pending })
    expect(out.h.state.dirty).toBe(true)
    expect(out.h.state.issues.rows[0]).toBeUndefined()
    await act(async () => root.unmount())
  })
})
