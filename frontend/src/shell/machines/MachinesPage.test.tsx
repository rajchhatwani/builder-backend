import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MachinesPage } from './MachinesPage'

const m = vi.hoisted(() => ({ machines: vi.fn(), issues: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  api: { getStateMachines: m.machines, getBehaviorIssues: m.issues },
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null; Object.values(m).forEach((f) => f.mockReset()) })

describe('MachinesPage', () => {
  it('still lists behaviour issues when the project has no state machines (F-0654)', async () => {
    m.machines.mockResolvedValue({ state_machines: [] })
    m.issues.mockResolvedValue({ issues: [{ message: 'hook points at a missing entity', path: 'hooks[0]' }] })
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    await act(async () => { root!.render(createElement(MachinesPage, { projectId: 'p' })) })
    for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve() })
    expect(host.querySelector('[data-testid=machines-empty]')).not.toBeNull()
    expect(host.textContent).toContain('hook points at a missing entity')
  })

  async function render() {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    await act(async () => { root!.render(createElement(MachinesPage, { projectId: 'p' })) })
    for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve() })
  }
  const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!

  it('shows an error and retries (F-0656)', async () => {
    m.machines.mockRejectedValueOnce(new Error('machines down'))
    m.issues.mockResolvedValue({ issues: [] })
    await render()
    expect(host.textContent).toContain('machines down')
    m.machines.mockResolvedValue({ state_machines: [] })
    await act(async () => { btn(/Try again/).click() })
    for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve() })
    expect(host.querySelector('[data-testid=machines-empty]')).not.toBeNull()
  })

  it('selecting a transition shows its detail, switching machine clears it (F-0656)', async () => {
    const mk = (entity: string) => ({ entity, field: 'status', initial: 'a', states: ['a', 'b'], transitions: [{ name: `go_${entity}`, from_states: ['a'], to_state: 'b' }] })
    m.machines.mockResolvedValue({ state_machines: [mk('Invoice'), mk('Leave')] })
    m.issues.mockResolvedValue({ issues: [] })
    await render()
    expect(host.querySelector('[data-testid=transition-detail-empty]')).not.toBeNull()
    await act(async () => { btn(/go_Invoice/).click() })
    expect(host.querySelector('[data-testid=transition-detail]')).not.toBeNull()
    await act(async () => { btn(/Leave/).click() })
    expect(host.querySelector('[data-testid=transition-detail-empty]')).not.toBeNull()
  })
})
