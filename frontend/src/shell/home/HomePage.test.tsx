import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { click, mount, byText } from '../ai/testUtils'
import { HomePage } from './HomePage'

const m = vi.hoisted(() => ({ dismiss: vi.fn(), refetch: vi.fn(), over: {} as Record<string, unknown> }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: { dismissStep: m.dismiss } }))
vi.mock('./useProjectStatus', () => ({
  useProjectStatus: () => ({
    isPending: false,
    isError: false,
    error: null,
    refetch: m.refetch,
    ...m.over,
    data: {
      ready: true,
      issues: [],
      counts: {},
      sections: [],
      next_step: { id: 'consider_auth', title: 't', reason: 'r', section: 'auth' },
    },
  }),
}))

describe('HomePage "Not now" (F-0647)', () => {
  it('stores the dismissal on the server, not in localStorage, then reloads the board', async () => {
    m.dismiss.mockResolvedValue({})
    m.refetch.mockResolvedValue({})
    localStorage.clear()
    const host = await mount(createElement(HomePage, { projectId: 'p1' }))
    await click(byText(host, 'button', /Not now/) ?? null)
    expect(m.dismiss).toHaveBeenCalledWith('p1', 'consider_auth')
    expect(m.refetch).toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
  })

  it('shows an error when the dismissal fails', async () => {
    m.dismiss.mockRejectedValue(new Error('nope'))
    const host = await mount(createElement(HomePage, { projectId: 'p1' }))
    await click(byText(host, 'button', /Not now/) ?? null)
    expect(host.textContent).toContain('nope')
  })
})

describe('HomePage states (F-0656)', () => {
  it('shows the error with a working Try again', async () => {
    m.over = { isError: true, error: new Error('status down'), data: undefined }
    m.refetch.mockClear()
    const host = await mount(createElement(HomePage, { projectId: 'p1' }))
    expect(host.textContent).toContain('status down')
    await click(byText(host, 'button', /Try again/) ?? null)
    expect(m.refetch).toHaveBeenCalled()
    m.over = {}
  })

  it('shows the ready banner', async () => {
    m.over = {}
    const host = await mount(createElement(HomePage, { projectId: 'p1' }))
    expect(host.querySelector('[data-testid=readiness-banner]')!.getAttribute('data-ready')).toBe('true')
  })
})
