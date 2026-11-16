import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { flush, mount } from '../../shell/ai/testUtils'
import { SimulatorTab } from './SimulatorTab'
import type { Catalogue } from './policyModel'

const m = vi.hoisted(() => ({ sim: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: { simulateAuthorization: m.sim } }))

const catalogue: Catalogue = { resource: { Post: {} }, subject: { id: 'uuid' }, roles: [], entities: [{ name: 'Post', ops: ['list', 'create'] }] }

describe('SimulatorTab (F-0566)', () => {
  it('sends the action that is shown, not a stale default', async () => {
    m.sim.mockResolvedValue({ allowed: true, reason: 'r', allow_matched: [], deny_matched: [], trace: [] })
    const host = await mount(createElement(SimulatorTab, { projectId: 'p', catalogue }))
    const sel = host.querySelectorAll('select')[1] as HTMLSelectElement
    expect(sel.value).toBe('list')
    await act(async () => { host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    await flush()
    expect(m.sim.mock.calls[0][1].op).toBe('list')
  })
})
