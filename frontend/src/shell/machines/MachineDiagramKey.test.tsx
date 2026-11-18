import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MachinesPage } from './MachinesPage'

const m = vi.hoisted(() => ({ machines: vi.fn(), issues: vi.fn(), mounts: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  api: { getStateMachines: m.machines, getBehaviorIssues: m.issues },
}))
vi.mock('./MachineDiagram', async () => {
  const { useEffect } = await import('react')
  return { default: () => { useEffect(() => { m.mounts() }, []); return null } }
})
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null })

describe('MachinesPage diagram', () => {
  it('remounts the diagram per machine so it is re-fitted (F-1314)', async () => {
    const mk = (entity: string) => ({ entity, field: 'status', initial: 'a', states: ['a', 'b'], transitions: [{ name: `go_${entity}`, from_states: ['a'], to_state: 'b' }] })
    m.machines.mockResolvedValue({ state_machines: [mk('Invoice'), mk('Leave')] })
    m.issues.mockResolvedValue({ issues: [] })
    host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
    await act(async () => { root!.render(createElement(MachinesPage, { projectId: 'p' })) })
    for (let i = 0; i < 8; i++) await act(async () => { await Promise.resolve() })
    expect(m.mounts).toHaveBeenCalledTimes(1)
    const b = [...host.querySelectorAll('button')].find((x) => /Leave/.test(x.textContent ?? ''))!
    await act(async () => { b.click() })
    expect(m.mounts).toHaveBeenCalledTimes(2)
  })
})
