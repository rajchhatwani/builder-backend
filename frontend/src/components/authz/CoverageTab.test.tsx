import { act, createElement, useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { flush, mount } from '../../shell/ai/testUtils'
import { CoverageTab } from './CoverageTab'

const m = vi.hoisted(() => ({ cov: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: { authorizationCoverage: m.cov } }))

let bump: () => void = () => {}
function Host() {
  const [v, setV] = useState(3)
  bump = () => setV(4)
  return createElement(CoverageTab, { projectId: 'p', version: v })
}
const result = (entity: string) => ({ model: 'pbac', rows: [{ entity, op: 'list', state: 'open', allow: [], deny: [] }] })

describe('CoverageTab (F-0569)', () => {
  it('ignores a stale response that resolves after a newer one', async () => {
    let r3: (v: unknown) => void = () => {}
    let r4: (v: unknown) => void = () => {}
    m.cov.mockImplementationOnce(() => new Promise((r) => { r3 = r })).mockImplementationOnce(() => new Promise((r) => { r4 = r }))
    const host = await mount(createElement(Host))
    await act(async () => { bump() })
    await act(async () => { r4(result('NewEntity')) })
    await flush()
    await act(async () => { r3(result('OldEntity')) })
    await flush()
    expect(host.textContent).toContain('NewEntity')
    expect(host.textContent).not.toContain('OldEntity')
  })
})
